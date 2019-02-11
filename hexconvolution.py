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


class Model(nn.Module):

    def __init__(self, board_size, layers, noise, noise_level, intermediate_channels=256, policy_channels=2, value_channels=1, value_intermediate_size=256, reach=1):
        #noise and switch rule not yet implemented
        super(Model, self).__init__()
        self.board_size = board_size
        self.policy_channels = policy_channels
        self.value_channels = value_channels
        self.conv = nn.Conv2d(2, intermediate_channels, kernel_size=reach*2+1, padding=reach)
        self.skiplayers = nn.ModuleList([SkipLayer(intermediate_channels, reach) for idx in range(layers)])
        self.policyconv = nn.Conv2d(intermediate_channels, policy_channels, kernel_size=1)
        self.policybn = nn.BatchNorm2d(policy_channels)
        self.policylin = nn.Linear(board_size**2 * policy_channels, board_size**2)
        self.valueconv = nn.Conv2d(intermediate_channels, value_channels, kernel_size=1)
        self.valuebn = nn.BatchNorm2d(value_channels)
        self.valuelin1 = nn.Linear(board_size**2 * value_channels, value_intermediate_size)
        self.valuelin2 = nn.Linear(value_intermediate_size, 1)

    def forward(self, x):
        illegal = x.sum(dim=1).view(1,-1)*10**10
        x = self.conv(x)
        for skiplayer in self.skiplayers:
            x = skiplayer(x)
        p = swish(self.policybn(self.policyconv(x))).view(-1, self.board_size**2 * self.policy_channels)
        p = F.log_softmax(self.policylin(p)-illegal, dim=1).view(-1, self.board_size, self.board_size)
        v = swish(self.valuebn(self.valueconv(x))).view(-1, self.board_size**2 * self.value_channels)
        v = swish(self.valuelin1(v))
        v = torch.tanh(self.valuelin2(v))
        return p, v


class NoMCTSModel(nn.Module):

    def __init__(self, board_size, layers, intermediate_channels=256, policy_channels=2, reach=1, switch=True):
        super(NoMCTSModel, self).__init__()
        self.board_size = board_size
        self.policy_channels = policy_channels
        self.conv = nn.Conv2d(2, intermediate_channels, kernel_size=reach*2+1, padding=reach)
        self.skiplayers = nn.ModuleList([SkipLayer(intermediate_channels, reach) for idx in range(layers)])
        self.policyconv = nn.Conv2d(intermediate_channels, policy_channels, kernel_size=1)
        self.policybn = nn.BatchNorm2d(policy_channels)
        self.policylin = nn.Linear(board_size**2 * policy_channels, board_size**2)

    def forward(self, x):
        #illegal moves are given a huge negative bias, so they are never selected for play - problem with noise?
        self.device=x.device
        x_sum = x.sum(dim=1).view(-1,self.board_size**2)
        illegal = x_sum * torch.exp(torch.tanh(x_sum.sum(dim=1)-1)*10).unsqueeze(1).expand_as(x_sum)- x_sum
        x = self.conv(x)
        for skiplayer in self.skiplayers:
            x = skiplayer(x)
        p = swish(self.policybn(self.policyconv(x))).view(-1, self.board_size**2 * self.policy_channels)
        return torch.sigmoid(self.policylin(p) - illegal)