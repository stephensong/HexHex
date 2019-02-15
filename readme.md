# HexHex v0.4

AlphaGo Zero adaptation of Hex. [Image of intend](https://user-images.githubusercontent.com/33026629/32346749-47b65b36-c049-11e7-9bac-08bc42cf9dae.png)

See [here](https://www.gwern.net/docs/rl/2017-silver.pdf) for full paper.


## Getting Started

* install prerequisites rename sample_config.ini to config.ini

* change parameters in config.ini

* run scripts in following order:
  * create_model.py
  * create_data.py
  * train.py
  * evaluate_two_models.py

### Prerequisites

* Python 3

* Pytorch (see [here](https://pytorch.org/get-started/locally/) for installation info)


## Features

* board representation with logic + switch rule

* network to evaluate positions
  * output activation of network is sigmoid for each stone
  * these are probabilities of how likely that stone wins the game
  * loss function is bewteen prediction of selected stone and outcome of game

* scripts for
  * creating models with hyperparameters
  * self-play to generate datasets
  * training and validating models
  * evaluating models against each other

* config to control parameters

* plenty of hyperparameters

* little documentation


## To-dos (somewhat chronological)

* batch-wise self-play

* more documentation

* make gui playable

* implement Monte Carlo tree search