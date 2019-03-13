#!/usr/bin/env python3

import argparse
import os
import time
from configparser import ConfigParser

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data.dataset import TensorDataset, ConcatDataset
from torch.utils.data.sampler import SubsetRandomSampler

import hex.utils.utils
from hex.model.hexconvolution import MCTSModel
from hex.utils.logger import logger


def get_args(config_file):
    config = ConfigParser()
    config.read(config_file)
    parser = argparse.ArgumentParser()
    parser.add_argument('--load_model', type=str, default=config.get('TRAIN', 'load_model'))
    parser.add_argument('--save_model', type=str, default=config.get('TRAIN', 'save_model'))
    parser.add_argument('--data', type=str, default=config.get('TRAIN', 'data'))
    parser.add_argument('--data_range_min', type=int, default=config.getint('TRAIN', 'data_range_min'))
    parser.add_argument('--data_range_max', type=int, default=config.getint('TRAIN', 'data_range_max'))
    parser.add_argument('--weight_decay', type=float, default=config.getfloat('TRAIN', 'weight_decay'))
    parser.add_argument('--batch_size', type=int, default=config.getint('TRAIN', 'batch_size'))
    parser.add_argument('--epochs', type=float, default=config.getfloat('TRAIN', 'epochs'))
    parser.add_argument('--samples_per_epoch', type=int, default=config.getint('TRAIN', 'samples_per_epoch'))
    parser.add_argument('--optimizer', type=str, default=config.get('TRAIN', 'optimizer'))
    parser.add_argument('--learning_rate', type=float, default=config.getfloat('TRAIN', 'learning_rate'))
    parser.add_argument('--validation_bool', type=bool, default=config.getboolean('TRAIN', 'validation_bool'))
    parser.add_argument('--validation_data', type=str, default=config.get('TRAIN', 'validation_data'))
    parser.add_argument('--save_every_epoch', type=bool, default=config.getboolean('TRAIN', 'save_every_epoch'))
    parser.add_argument('--print_loss_frequency', type=int, default=config.getint('TRAIN', 'print_loss_frequency'))
    return parser.parse_args(args=[])

class LossTriple:
    def __init__(self, value_loss, policy_loss, param_loss):
        self.value = value_loss
        self.policy = policy_loss
        self.param = param_loss

    def total(self):
        return self.value + self.policy + self.param

class TrainingStats:
    def __init__(self):
        self.stats = {
            'value': {'train': [], 'val': []},
            'policy': {'train': [], 'val': []},
            'param': {'train': [], 'val': []},
        }


    def add_batch(self, phase: str, epoch: int, batch_idx: int, loss: LossTriple):
        for type in self.all_loss_types():
            epochs = self.stats[type][phase]
            if epoch >= len(epochs):
                epochs.append([])
            batches = epochs[epoch]
            if batch_idx >= len(batches):
                batches.append([])
            batch = batches[batch_idx]
            batch.append(loss.__getattribute__(type))

    @staticmethod
    def all_loss_types():
        return ['value', 'policy', 'param']

    def get_epoch_mean(self, loss_type: str, phase: str, epoch = -1):
        if loss_type == 'total':
            return sum(self.get_epoch_mean(t, phase, epoch) for t in self.all_loss_types())
        return np.mean(self.stats[loss_type][phase][epoch]).item()

    def last_values_to_string(self):
        return "total: {:.3f} {:.3f} | value: {:.3f} {:.3f} | policy: {:.3f} {:.3f} | param: {:.3f} {:.3f} | train val".format(
                self.get_epoch_mean('total', 'train'),
                self.get_epoch_mean('total', 'val'),
                self.get_epoch_mean('value', 'train'),
                self.get_epoch_mean('value', 'val'),
                self.get_epoch_mean('policy', 'train'),
                self.get_epoch_mean('policy', 'val'),
                self.get_epoch_mean('param', 'train'),
                self.get_epoch_mean('param', 'val'),
        )


class Training:
    def __init__(self, args, model, optimizer):
        self.args = args
        self.model = model
        self.log_file = os.path.join('logs', args.save_model + '.csv')
        with open(self.log_file, 'w') as log:
            log.write('# batch val_loss pred_loss weighted_param_loss duration[s]\n')
        self.device = hex.utils.utils.device
        self.optimizer = optimizer
        self.stats = TrainingStats()

    def train_mcts_model(self, train_dataset, val_dataset):
        mean_epoch_loss_history = {'train': [], 'val': []}
        for epoch in range(int(self.args.epochs)):
            sampler = SubsetRandomSampler(torch.randperm(len(train_dataset))[:self.args.samples_per_epoch])
            train_loader = torch.utils.data.DataLoader(train_dataset, batch_size=self.args.batch_size, sampler=sampler)
            val_loader = torch.utils.data.DataLoader(val_dataset, batch_size=self.args.batch_size)
            dataloaders = {'train': train_loader, 'val': val_loader}

            for phase in ['val', 'train']: # run validation first, s.t. loss values are from the same network
                for i, (board_states, policies_train, value_train) in enumerate(dataloaders[phase], 0):
                    board_states, policies_train, value_train \
                        = board_states.to(self.device), policies_train.to(self.device), value_train.to(self.device)

                    self.optimizer.zero_grad()
                    with torch.set_grad_enabled(phase == 'train'):
                        param_loss, policy_loss, value_loss = self.measure_mean_losses(
                                board_states,
                                policies_train,
                                value_train
                        )

                        loss = policy_loss + value_loss + param_loss

                        loss_triple = LossTriple(value_loss.item(), policy_loss.item(), param_loss.item())
                        self.stats.add_batch(phase, epoch, i, loss_triple)

                        if phase == 'train':
                            loss.backward()
                            self.optimizer.step()

                # mean_epoch_loss_history[phase].append(
                #         {key: value / len(dataloaders[phase].dataset) for key, value in running_losses.items()}
                # )

            logger.info('Epoch [%3d] mini-batches [%8d] %s'
                        % (epoch, epoch * len(train_loader), self.stats.last_values_to_string())
                        )
            if self.args.save_every_epoch:
                file_name = 'models/{}_{}.pt'.format(self.args.save_model, epoch)
                torch.save(self.model, file_name)
                print(f'wrote {file_name}')

        if not self.args.save_every_epoch:
            file_name = 'models/{}.pt'.format(self.args.save_model)
            torch.save(self.model, file_name)
            print(f'wrote {file_name}')

        print('Finished Training\n')

    def measure_mean_losses(self, board_states, policies_train, value_train):
        policies_log, values_out = self.model(board_states)
        policies_train_entropy = torch.distributions.Categorical(probs=policies_train).entropy()
        # this calculated cross entropy as policy output is log(p)
        # subtracting policies_train_entropy, s.t. policy_loss == 0 if both policies are equal
        policy_loss = torch.mean(torch.sum(-policies_log * policies_train, dim=1) - policies_train_entropy)
        value_loss_fct = nn.MSELoss(reduction='mean')
        value_loss = value_loss_fct(values_out, value_train)
        param_loss = self.args.weight_decay * \
                     sum(torch.pow(p, 2).sum() for p in self.model.parameters())
        return param_loss, policy_loss, value_loss



def train_model(model, save_model_path, dataloader, criterion, optimizer, epochs, device, weight_decay,
                save_every_epoch, print_loss_frequency, validation_triple):
    log_file = os.path.join('logs', save_model_path + '.csv')

    with open(log_file, 'w') as log:
        log.write('# batch val_loss pred_loss weighted_param_loss duration[s]\n')

    start = time.time()

    '''
    trains model with backpropagation, loss criterion is currently binary cross-entropy and optimizer is adadelta
    '''
    for epoch in range(epochs):

        running_loss = 0.0
        observed_states = 0

        for i, (board_states, moves, labels) in enumerate(dataloader, 0):
            board_states, moves, labels = board_states.to(device), moves.to(device), labels.to(device)

            optimizer.zero_grad()

            outputs = model(board_states)
            output_values = torch.gather(outputs, 1, moves)

            loss = criterion(output_values.view(-1), labels)
            loss.backward()
            optimizer.step()

            batch_size = board_states.shape[0]
            running_loss += loss.item()
            observed_states += batch_size

            if i % print_loss_frequency == 0:
                l2loss = sum(torch.pow(p, 2).sum() for p in model.parameters() if p.requires_grad)
                weighted_param_loss = weight_decay * l2loss
                if validation_triple is not None:
                    with torch.no_grad():
                        num_validations = len(validation_triple[0])
                        val_pred_tensor = model(validation_triple[0])
                        val_values = torch.gather(val_pred_tensor, 1, validation_triple[1])
                        val_loss = criterion(val_values.view(-1), validation_triple[2])
                    duration = int(time.time() - start)
                    print(
                            'batch %3d / %3d val_loss: %.3f  pred_loss: %.3f pred_loss_batch: %.3f  l2_param_loss: %.3f weighted_param_loss: %.3f'
                            % (
                                i + 1, len(dataloader), val_loss / num_validations, loss.item() / batch_size,
                                loss.item(),
                                l2loss, weighted_param_loss))
                    with open(log_file, 'a') as log:
                        log.write(
                                f'{i + 1} {val_loss / num_validations} {loss.item() / batch_size} {weighted_param_loss} {duration}\n')
                else:
                    print('batch %3d / %3d pred_loss: %.3f  l2_param_loss: %.3f weighted_param_loss: %.3f'
                          % (i + 1, len(dataloader), loss.item() / batch_size, l2loss, weighted_param_loss))

        l2loss = sum(torch.pow(p, 2).sum() for p in model.parameters() if p.requires_grad)
        weighted_param_loss = weight_decay * l2loss
        print('Epoch [%d] pred_loss: %.3f l2_param_loss: %.3f weighted_param_loss: %.3f'
              % (epoch + 1, running_loss / observed_states, l2loss, weighted_param_loss))
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
    '''
    loads data and sets criterion and optimizer for train_model
    '''
    print("=== training model ===")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    dataset_list = []
    for idx in range(args.data_range_min, args.data_range_max):
        board_states, moves, targets = torch.load('data/{}_{}.pt'.format(args.data, idx))
        dataset_list.append(TensorDataset(board_states, moves, targets))
    concat_dataset = ConcatDataset(dataset_list)
    total_len = len(concat_dataset)
    val_fraction = .1
    val_part = int(val_fraction * total_len)
    train_dataset, val_dataset = torch.utils.data.random_split(concat_dataset, [total_len - val_part, val_part])
    if args.epochs < 1:
        concat_len = train_dataset.__len__()
        sampler = SubsetRandomSampler(torch.randperm(concat_len)[:int(concat_len * args.epochs)])
        train_loader = torch.utils.data.DataLoader(train_dataset, batch_size=args.batch_size, sampler=sampler,
                                                     num_workers=0)
        args.epochs = 1
    else:
        train_loader = torch.utils.data.DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True,
                                                     num_workers=0)

    model = torch.load('models/{}.pt'.format(args.load_model), map_location=device)
    nn.DataParallel(model).to(device)

    # don't use weight_decay in optimizer for MCTSModel, as the outcome is more predictable if measured in loss directly
    optimizer_weight_decay = 0 if model.__class__ == MCTSModel else args.weight_decay
    if args.optimizer == 'adadelta':
        optimizer = optim.Adadelta(model.parameters(), weight_decay=optimizer_weight_decay)
    elif args.optimizer == 'sgd':
        optimizer = optim.SGD(model.parameters(), lr=args.learning_rate, momentum=0.9,
                              weight_decay=optimizer_weight_decay)
    else:
        optimizer = optim.Adam(model.parameters(), lr=args.learning_rate, weight_decay=optimizer_weight_decay)

    val_triple = None
    if args.validation_bool:
        val_board_tensor, val_moves_tensor, val_target_tensor = torch.load(f'data/{args.validation_data}.pt')
        val_triple = (val_board_tensor.to(device), val_moves_tensor.to(device), val_target_tensor.to(device))

    if model.__class__ == MCTSModel:
        training = Training(args, model, optimizer)
        training.train_mcts_model(train_dataset, val_dataset)
    else:
        criterion = nn.BCELoss(reduction='sum')
        train_model(model, args.save_model, train_loader, criterion, optimizer, int(args.epochs), device,
                    args.weight_decay, args.save_every_epoch, args.print_loss_frequency, val_triple)


def train_by_config_file(config_file):
    args = get_args(config_file)
    train(args)


if __name__ == "__main__":
    train_by_config_file('config.ini')