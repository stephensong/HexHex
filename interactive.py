#!/usr/bin/env python3

from configparser import ConfigParser
import argparse
import torch
from hexboard import Board
from hexgame import MultiHexGame
from visualization.gui import Gui

def get_args():
    config = ConfigParser()
    config.read('config.ini')
    parser = argparse.ArgumentParser()

    parser.add_argument('--model', type=str, default=config.get('INTERACTIVE', 'model'))
    parser.add_argument('--temperature', type=float, default=config.get('INTERACTIVE', 'temperature'))
    parser.add_argument('--first_move_ai', type=bool, default=config.getboolean('INTERACTIVE', 'first_move_ai'))
    parser.add_argument('--gui_radius', type=int, default=config.get('INTERACTIVE', 'gui_radius'))

    return parser.parse_args()

class InteractiveGame:
    def __init__(self, args):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = torch.load('models/{}.pt'.format(args.model), map_location=self.device)

        self.board = Board(size=self.model.board_size)
        self.game = MultiHexGame((self.board,), (self.model,), self.device, temperature=args.temperature)
        self.gui = Gui(self.board, args.gui_radius)

    def play_human_move(self):
        move = self.get_move()
        self.board.set_stone(move)
        self.gui.update_board(self.board)

        if self.board.winner:
            print("Player has won!")
            self.wait_for_gui_exit()

    def play_ai_move(self):
        move_ratings = self.game.batched_single_move(self.model)
        self.gui.update_board(self.board, move_ratings=move_ratings)
        if self.board.winner:
            print("agent has won!")
            self.wait_for_gui_exit()

    def wait_for_gui_exit(self):
        while True:
            self.gui.get_cell()

    def get_move(self):
        while True:
            move = self.gui.get_cell()
            if move in self.board.legal_moves:
                return move

def _main():
    args = get_args()
    interactive = InteractiveGame(args)

    if args.first_move_ai:
        interactive.play_ai_move()
    while True:
        interactive.play_human_move()
        interactive.play_ai_move()


if __name__ == '__main__':
    _main()