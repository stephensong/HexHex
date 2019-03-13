import torch
import torch.nn as nn
import torch.nn.functional as F


def swish(x):
    return x * torch.sigmoid(x)


class SkipLayer(nn.Module):

    def __init__(self, channels, reach):
        super(SkipLayer, self).__init__()
        self.conv = nn.Conv2d(channels, channels, kernel_size=reach*2+1, padding=reach)
        self.bn = nn.BatchNorm2d(channels)

    def forward(self, x):
        return swish(x + self.bn(self.conv(x)))


class SkipLayerAlpha(nn.Module):

    def __init__(self, channels, reach):
        super(SkipLayerAlpha, self).__init__()
        self.conv1 = nn.Conv2d(channels, channels, kernel_size=reach*2+1, padding=reach)
        self.conv2 = nn.Conv2d(channels, channels, kernel_size=reach*2+1, padding=reach)
        self.bn1 = nn.BatchNorm2d(channels)
        self.bn2 = nn.BatchNorm2d(channels)

    def forward(self, x):
        y = F.relu(self.bn1(self.conv1(x)))
        x = x + self.bn2(self.conv2(y))
        return F.relu(x)


class NoMCTSModel(nn.Module):
    '''
    model consists of a convolutional layer to change the number of channels from (three) input channels to intermediate channels
    then a specified amount of residual or skip-layers https://en.wikipedia.org/wiki/Residual_neural_network
    then policy_channels sum over the different channels and a fully connected layer to get output in shape of the board
    the last sigmoid function converts all values to probabilities: interpretable as probability to win the game when making this move
    '''
    def __init__(self, board_size, layers, intermediate_channels=256, policy_channels=2, reach_conv=1, skip_layer='single'):
        super(NoMCTSModel, self).__init__()
        self.board_size = board_size
        self.policy_channels = policy_channels
        self.conv = nn.Conv2d(3, intermediate_channels, kernel_size=reach_conv*2+1, padding=reach_conv)
        if skip_layer=='alpha':
            self.skiplayers = nn.ModuleList([SkipLayerAlpha(intermediate_channels, 1) for idx in range(layers)])
        else:
            self.skiplayers = nn.ModuleList([SkipLayer(intermediate_channels, 1) for idx in range(layers)])
        self.policyconv = nn.Conv2d(intermediate_channels, policy_channels, kernel_size=1)
        self.policybn = nn.BatchNorm2d(policy_channels)
        self.policylin = nn.Linear(board_size**2 * policy_channels, board_size**2)

    def forward(self, x):
        #illegal moves are given a huge negative bias, so they are never selected for play
        x_sum = (x[:,0]+x[:,1]).view(-1,self.board_size**2)
        illegal = x_sum * torch.exp(torch.tanh((x_sum.sum(dim=1)-1)*1000)*10).unsqueeze(1).expand_as(x_sum) - x_sum
        x = self.conv(x)
        for skiplayer in self.skiplayers:
            x = skiplayer(x)
        p = swish(self.policybn(self.policyconv(x))).view(-1, self.board_size**2 * self.policy_channels)
        return torch.sigmoid(self.policylin(p) - illegal)


class MCTSModel(nn.Module):
    def __init__(self, board_size, layers, intermediate_channels=256, policy_channels=2, value_channels=1, value_intermediate_fcn=256, reach_conv=1, skip_layer='single'):
        super(MCTSModel, self).__init__()
        self.board_size = board_size
        self.policy_channels = policy_channels
        self.value_channels = value_channels
        self.conv = nn.Conv2d(3, intermediate_channels, kernel_size=reach_conv*2+1, padding=reach_conv)
        if skip_layer=='alpha':
            self.skiplayers = nn.ModuleList([SkipLayerAlpha(intermediate_channels, 1) for idx in range(layers)])
        else:
            self.skiplayers = nn.ModuleList([SkipLayer(intermediate_channels, 1) for idx in range(layers)])
        self.policyconv = nn.Conv2d(intermediate_channels, policy_channels, kernel_size=1)
        self.policybn = nn.BatchNorm2d(policy_channels)
        self.policylin = nn.Linear(board_size**2 * policy_channels, board_size**2)
        self.valueconv = nn.Conv2d(intermediate_channels, value_channels, kernel_size=1)
        self.valuebn = nn.BatchNorm2d(value_channels)
        self.valuelin1 = nn.Linear(board_size**2 * value_channels, value_intermediate_fcn)
        self.valuelin2 = nn.Linear(value_intermediate_fcn, 1)

    def forward(self, x):
        """
        Returns log probabilities
        """
        x_sum = (x[:,0]+x[:,1]).view(-1,self.board_size**2)
        illegal = x_sum * torch.exp(torch.tanh((x_sum.sum(dim=1)-1)*1000)*10).unsqueeze(1).expand_as(x_sum) - x_sum
        x = self.conv(x)
        for skiplayer in self.skiplayers:
            x = skiplayer(x)
        p = swish(self.policybn(self.policyconv(x))).view(-1, self.board_size**2 * self.policy_channels)
        p = F.log_softmax(self.policylin(p)-illegal, dim=1)
        v = swish(self.valuebn(self.valueconv(x))).view(-1, self.board_size**2 * self.value_channels)
        v = swish(self.valuelin1(v))
        v = torch.tanh(self.valuelin2(v))
        return p, v


class RandomModel(nn.Module):
    '''
    outputs 0.5 for every legal move
    makes random moves if temperature*temperature_decay > 0
    '''
    def __init__(self, board_size):
        super(RandomModel, self).__init__()
        self.board_size = board_size

    def forward(self, x):
        double_stones = (x[:,0]*x[:,1]).view(-1,self.board_size**2)
        stone_bool = (x[:,0]+x[:,1]).view(-1,self.board_size**2)-double_stones
        return 0.5*(torch.ones_like(stone_bool)-torch.sigmoid(((1000*double_stones+stone_bool).sum(dim=1)-1.5)*200).unsqueeze(1).expand_as(stone_bool)*stone_bool)