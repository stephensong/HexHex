import torch
import torch.nn as nn
import torch.optim as optim

from torch.utils.data.dataset import TensorDataset, ConcatDataset

import os
import argparse
from configparser import ConfigParser

def get_args(config_file):
    config = ConfigParser()
    config.read(config_file)
    parser = argparse.ArgumentParser()
    parser.add_argument('--load_model', type=str, default=config.get('TRAIN', 'load_model'))
    parser.add_argument('--save_model', type=str, default=config.get('TRAIN', 'save_model'))
    parser.add_argument('--data', type=str, default=config.get('TRAIN', 'data'))
    parser.add_argument('--data_range_min', type=int, default=config.get('TRAIN', 'data_range_min'))
    parser.add_argument('--data_range_max', type=int, default=config.get('TRAIN', 'data_range_max'))
    parser.add_argument('--weight_decay', type=float, default=config.get('TRAIN', 'weight_decay'))
    parser.add_argument('--batch_size', type=int, default=config.get('TRAIN', 'batch_size'))
    parser.add_argument('--epochs', type=int, default=config.get('TRAIN', 'epochs'))
    parser.add_argument('--validation_bool', type=bool, default=config.getboolean('TRAIN', 'validation_bool'))
    parser.add_argument('--validation_data', type=str, default=config.get('TRAIN', 'validation_data'))
    parser.add_argument('--save_every_epoch', type=bool, default=config.getboolean('TRAIN', 'save_every_epoch'))
    parser.add_argument('--print_loss_frequency', type=int, default=config.get('TRAIN', 'print_loss_frequency'))
    return parser.parse_args()

def train_model(model, save_model_path, dataloader, criterion, optimizer, epochs, device, save_every_epoch=False, print_loss_frequency=100, validation_triple=None):

    for epoch in range(epochs):  # loop over the dataset multiple times

        running_loss = 0.0
        observed_states = 0

        for i, (board_states, moves, labels) in enumerate(dataloader, 0):
            # get the inputs
            board_states, moves, labels = board_states.to(device), moves.to(device), labels.to(device)

            # zero the parameter gradients
            optimizer.zero_grad()

            # forward + backward + optimize
            outputs = model(board_states)
            output_values = torch.gather(outputs, 1, moves)

            loss = criterion(output_values.view(-1), labels)
            loss.backward()
            optimizer.step()

            batch_size = board_states.shape[0]
            running_loss += loss.item()
            observed_states += batch_size

            if i % print_loss_frequency == print_loss_frequency - 1:
                l2loss = sum(torch.pow(p, 2).sum() for p in model.parameters() if p.requires_grad)
                if validation_triple is not None:
                    with torch.no_grad():
                        val_pred_tensor = model(validation_triple[0])
                        val_values = torch.gather(val_pred_tensor, 1, validation_triple[1])
                        val_loss = criterion(val_values.view(-1), validation_triple[2])
                    print('batch %3d / %3d val_loss: %.3f  pred_loss: %.3f  l2_param_loss: %.3f'
                          %(i + 1, len(dataloader), val_loss, loss.item() / batch_size, l2loss))
                else:
                    print('batch %3d / %3d pred_loss: %.3f  l2_param_loss: %.3f'
                          %(i + 1, len(dataloader), loss.item() / batch_size, l2loss))


        l2loss = sum(torch.pow(p, 2).sum() for p in model.parameters() if p.requires_grad)
        print('Epoch [%d] pred_loss: %.3f l2_param_loss: %.3f' %(epoch + 1, running_loss / observed_states, l2loss))
        if save_every_epoch:
            file_name = 'models/{}_{}.pt'.format(save_model_path, epoch)
            torch.save(model, file_name)
            print(f'wrote {file_name}')

    if not save_every_epoch:
        file_name = 'models/{}.pt'.format(save_model_path)
        torch.save(model, file_name)
        print(f'wrote {file_name}')

    print('Finished Training\n')

def train(args):
    print("=== training model ===")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    dataset_list = []
    for idx in range(args.data_range_min, args.data_range_max):
        board_states, moves, targets = torch.load('data/{}_{}.pt'.format(args.data, idx))
        dataset_list.append(TensorDataset(board_states, moves, targets))
    concat_dataset = ConcatDataset(dataset_list)
    positionloader = torch.utils.data.DataLoader(concat_dataset, batch_size=args.batch_size, shuffle=True, num_workers=0)

    model = torch.load('models/{}.pt'.format(args.load_model), map_location=device)
    model.to(device)

    criterion = nn.MSELoss(reduction='sum')
    optimizer = optim.Adadelta(model.parameters(), weight_decay=args.weight_decay)

    val_triple = None
    if args.validation_bool:
        val_board_tensor, val_moves_tensor, val_target_tensor = torch.load(f'data/{args.validation_data}.pt')
        val_triple = (val_board_tensor.to(device), val_moves_tensor.to(device), val_target_tensor.to(device))
    train_model(model, args.save_model, positionloader, criterion, optimizer, args.epochs, device,
                args.save_every_epoch, args.print_loss_frequency, val_triple)


def train_by_config_file(config_file):
    args = get_args(config_file)
    train(args)

if __name__ == "__main__":
    train_by_config_file('config.ini')