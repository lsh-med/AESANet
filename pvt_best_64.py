import torch
import torch.nn as nn
import torch.nn.functional as F
from pvtv2 import pvt_v2_b2
import cv2
from torch.nn import CrossEntropyLoss, Dropout, Softmax, Linear, Conv2d, LayerNorm, Parameter
from decoder_p import MSA_head
from torch.nn import functional as F
import os
import torch
import torch.nn as nn
import torch.nn.functional as F
import logging
import math
import os
import numpy as np
from einops import rearrange
from einops.layers.torch import Rearrange, Reduce
import torch
from torch import nn
from torch.nn import CrossEntropyLoss, MSELoss
from einops import rearrange
from torchvision import models

import math

#########
import torch
import torch.nn as nn
import torch.nn.functional as F
import warnings
from torch.nn import CrossEntropyLoss, Dropout, Softmax, Linear, Conv2d, LayerNorm, Parameter
from torch.nn import Module


class BasicConv2d(nn.Module):
    def __init__(self, in_planes, out_planes, kernel_size, stride=1, padding=0, dilation=1):
        super(BasicConv2d, self).__init__()

        self.conv = nn.Conv2d(in_planes, out_planes,
                              kernel_size=kernel_size, stride=stride,
                              padding=padding, dilation=dilation, bias=False)
        self.bn = nn.BatchNorm2d(out_planes)
        self.relu = nn.ReLU(inplace=True)

    def forward(self, x):
        x = self.conv(x)
        x = self.bn(x)
        x = self.relu(x)
        return x


class conv2d(nn.Module):
    def __init__(self, in_c, out_c, kernel_size=3, padding=1, dilation=1, act=True):
        super().__init__()
        self.act = act

        self.conv = nn.Sequential(
            nn.Conv2d(in_c, out_c, kernel_size, padding=padding, dilation=dilation, bias=False),
            nn.BatchNorm2d(out_c)
        )
        self.relu = nn.ReLU(inplace=True)

    def forward(self, x):
        x = self.conv(x)
        if self.act == True:
            x = self.relu(x)
        return x


class channel_bind(nn.Module):
    def __init__(self, in_ch, out_ch, bilinear=True):
        super(channel_bind, self).__init__()

        self.r1 = ResidualBlock(in_ch + out_ch, out_ch)
        self.r2 = ResidualBlock(out_ch, out_ch)

    def forward(self, x1, x2):
        x = torch.cat([x2, x1], dim=1)
        x = self.r1(x)
        x = self.r2(x)
        #    x = self.p1(x, masks)
        return x


class up(nn.Module):
    def __init__(self, in_ch, out_ch, bilinear=True):
        super(up, self).__init__()

        self.upsample = nn.ConvTranspose2d(in_ch, in_ch, kernel_size=4, stride=2, padding=1)
        self.r1 = ResidualBlock(in_ch + out_ch, out_ch)
        self.r2 = ResidualBlock(out_ch, out_ch)

        self.p1 = MixPool(out_ch, out_ch)

    def forward(self, x1, x2):
        x1 = self.upsample(x1)
        x = torch.cat([x2, x1], dim=1)
        x = self.r1(x)
        x = self.r2(x)
        #    x = self.p1(x, masks)
        return x


class outconv(nn.Module):
    def __init__(self, in_ch, out_ch, dropout=False, rate=0.1):
        super(outconv, self).__init__()
        self.dropout = dropout
        if dropout:
            print('dropout', rate)
            self.dp = nn.Dropout2d(rate)
        self.conv = nn.Conv2d(in_ch, out_ch, 1)

    def forward(self, x):
        if self.dropout:
            x = self.dp(x)
        x = self.conv(x)
        return x


class BCA(nn.Module):
    def __init__(self, xin_channels, yin_channels, mid_channels, BatchNorm=nn.BatchNorm2d, scale=False):
        super(BCA, self).__init__()
        self.mid_channels = mid_channels
        self.f_self = nn.Sequential(
            nn.Conv2d(in_channels=xin_channels, out_channels=mid_channels,
                      kernel_size=1, stride=1, padding=0, bias=False),
            BatchNorm(mid_channels),
            nn.Conv2d(in_channels=mid_channels, out_channels=mid_channels,
                      kernel_size=1, stride=1, padding=0, bias=False),
            BatchNorm(mid_channels),
        )
        self.f_x = nn.Sequential(
            nn.Conv2d(in_channels=xin_channels, out_channels=mid_channels,
                      kernel_size=1, stride=1, padding=0, bias=False),
            BatchNorm(mid_channels),
            nn.Conv2d(in_channels=mid_channels, out_channels=mid_channels,
                      kernel_size=1, stride=1, padding=0, bias=False),
            BatchNorm(mid_channels),
        )
        self.f_y = nn.Sequential(
            nn.Conv2d(in_channels=yin_channels, out_channels=mid_channels,
                      kernel_size=1, stride=1, padding=0, bias=False),
            BatchNorm(mid_channels),
            nn.Conv2d(in_channels=mid_channels, out_channels=mid_channels,
                      kernel_size=1, stride=1, padding=0, bias=False),
            BatchNorm(mid_channels),
        )
        self.f_up = nn.Sequential(
            nn.Conv2d(in_channels=mid_channels, out_channels=xin_channels,
                      kernel_size=1, stride=1, padding=0, bias=False),
            BatchNorm(xin_channels),
        )
        self.scale = scale
        nn.init.constant_(self.f_up[1].weight, 0)
        nn.init.constant_(self.f_up[1].bias, 0)

    def forward(self, x, y):
        orginal = x

        batch_size = x.size(0)
        #     x = F.interpolate(x, size=(11,11), mode='bilinear')
        y = F.interpolate(y, size=x.size()[2:], mode='bilinear')
        batch_size = x.size(0)
        fself = self.f_self(x).view(batch_size, self.mid_channels, -1)
        fself = fself.permute(0, 2, 1)
        fx = self.f_x(x).view(batch_size, self.mid_channels, -1)
        fx = fx.permute(0, 2, 1)
        fy = self.f_y(y).view(batch_size, self.mid_channels, -1)
        sim_map = torch.matmul(fx, fy)
        if self.scale:
            sim_map = (self.mid_channels ** -.5) * sim_map
        sim_map_div_C = F.softmax(sim_map, dim=-1)
        fout = torch.matmul(sim_map_div_C, fself)
        fout = fout.permute(0, 2, 1).contiguous()
        fout = fout.view(batch_size, self.mid_channels, *x.size()[2:])
        out = self.f_up(fout)
        out = F.interpolate(out, size=orginal.size()[2:], mode='bilinear')
        return orginal + out


class ConvBNReLU(nn.Module):
    def __init__(self, in_channels, out_channels=64, kernel_size=3):
        super(ConvBNReLU, self).__init__()

        padding = kernel_size // 2
        self.conv = nn.Conv2d(in_channels=in_channels, out_channels=out_channels, kernel_size=kernel_size, stride=1,
                              padding=padding)
        self.bn = nn.BatchNorm2d(out_channels)
        self.relu = nn.ReLU(inplace=True)

    def forward(self, x):
        x = self.conv(x)
        x = self.bn(x)
        x = self.relu(x)
        return x

class non_bottleneck_1d(nn.Module):
    def __init__(self, chann, dropprob, dilated):
        super().__init__()
        self.conv3x1_1 = nn.Conv2d(chann, chann, (3, 1), stride=1, padding=(1, 0), bias=True)
        self.conv1x3_1 = nn.Conv2d(chann, chann, (1, 3), stride=1, padding=(0, 1), bias=True)
        self.bn1 = nn.BatchNorm2d(chann, eps=1e-03)
        self.conv3x1_2 = nn.Conv2d(chann, chann, (3, 1), stride=1, padding=(1 * dilated, 0), bias=True,
                                   dilation=(dilated, 1))
        self.conv1x3_2 = nn.Conv2d(chann, chann, (1, 3), stride=1, padding=(0, 1 * dilated), bias=True, dilation=(1, dilated))
        self.bn2 = nn.BatchNorm2d(chann, eps=1e-03)
        self.dropout = nn.Dropout2d(dropprob)

    def forward(self, input):
        output = self.conv3x1_1(input)
        output = F.relu(output)
        output = self.conv1x3_1(output)
        output = self.bn1(output)
        output = F.relu(output)
        output = self.conv3x1_2(output)
        output = F.relu(output)
        output = self.conv1x3_2(output)
        output = self.bn2(output)

        if (self.dropout.p != 0):
            output = self.dropout(output)

        return F.relu(output + input)

class RF2B(nn.Module):
    def __init__(self, in_c, inter_channels):
        super().__init__()

        self.conv5a = nn.Sequential(nn.Conv2d(in_c, inter_channels, 3, padding=1, bias=False),
                                    nn.BatchNorm2d(inter_channels),
                                    nn.ReLU())
        self.c1 = nn.Sequential(non_bottleneck_1d(inter_channels, 0.3, 1))
        self.c2 = nn.Sequential(non_bottleneck_1d(inter_channels, 0.3, 3))
        self.c3 = nn.Sequential(non_bottleneck_1d(inter_channels, 0.3, 5))
        self.c4 = nn.Sequential(non_bottleneck_1d(inter_channels, 0.3, 7))
        self.c_bind = self.conv_cat = nn.Sequential(
            nn.Conv2d(inter_channels * 3, inter_channels, kernel_size=1),
            nn.BatchNorm2d(inter_channels)
        )
     #   self.c6 = nn.Sequential(nn.Dropout2d(0.1, False), nn.Conv2d(inter_channels, out_c, 1))

        self.relu = nn.ReLU(True)


    def forward(self, x):
        feat1 = self.conv5a(x)
        #  sc = self.sc(feat1)
        x1 = self.c1(feat1)
        x2 = self.c2(feat1 + x1)
        x3 = self.c3(feat1 + x2)
        x4 = self.c4(feat1 + x3)
        xc = torch.cat([x2, x3, x4], axis=1)
        xc = self.c_bind(xc)
        x = self.relu(x1 + xc)
        return x


class LCA(nn.Module):
    def __init__(self):
        super(LCA, self).__init__()

    def forward(self, x, pred):
        residual = x
        score = torch.sigmoid(pred)
        dist = torch.abs(score - 0.5)
        att = 1 - (dist / 0.5)

        # att_max = torch.max(att)
        # att_min = torch.min(att)
        # att_map = (att_map-att_min)/(att_max-att_min)
        # print(att_map)
        att_x = x * att

        out = att_x + residual

        return out



class PolypPVT(nn.Module):
    def __init__(self, channel=64):
        super(PolypPVT, self).__init__()

        self.backbone = pvt_v2_b2()  # [64, 128, 320, 512]
        path = './pretrained_pth/pvt_v2_b2.pth'
        save_model = torch.load(path)
        model_dict = self.backbone.state_dict()
        state_dict = {k: v for k, v in save_model.items() if k in model_dict.keys()}
        model_dict.update(state_dict)
        self.backbone.load_state_dict(model_dict)

        self.res1 = ResidualBlock(64, 64)
        self.res2 = ResidualBlock(32, 32)
        self.res3 = ResidualBlock(16, 16)

   #     self.re_conv1 = ConvBNReLU(in_channels=64, out_channels=channel, kernel_size=3)
   #     self.re_conv2 = ConvBNReLU(in_channels=128, out_channels=channel, kernel_size=3)
   #     self.re_conv3 = ConvBNReLU(in_channels=320, out_channels=channel, kernel_size=3)
   #     self.re_conv4 = ConvBNReLU(in_channels=512, out_channels=channel, kernel_size=3)

        self.bca1 = BCA(64, 64, 64, nn.BatchNorm2d)
        self.bca2 = BCA(64, 64, 64, nn.BatchNorm2d)
        self.bca3 = BCA(64, 64, 64, nn.BatchNorm2d)
        self.bca4 = BCA(64, 64, 64, nn.BatchNorm2d)

        self.c3 = nn.Conv2d(128, 1, kernel_size=1)
        self.c4 = nn.Conv2d(320, 1, kernel_size=1)
        self.c5 = nn.Conv2d(512, 1, kernel_size=1)

        self.gate1 = GatedConv(32, 32)
        self.gate2 = GatedConv(16, 16)
        self.gate3 = GatedConv(8, 8)

        #   self.s1 = dilated_conv(64, 64)
        #   self.s2 = dilated_conv(128, 128)
        #   self.s3 = dilated_conv(320, 320)
        #  self.s4 = dilated_conv(512, 512)

        #   self.m1 = multikernel_dilated_conv(64, 64)
        #   self.m2 = multikernel_dilated_conv(128, 128)
        #   self.m3 = multikernel_dilated_conv(320, 320)
        #   self.m4 = multikernel_dilated_conv(512, 512)
        self.f1 = RF2B(64,64)
        self.f2 = RF2B(128,64)
        self.f3 = RF2B(320,64)
        self.f4 = RF2B(512,64)

        self.d0 = nn.Conv2d(64, 64, kernel_size=1)
        self.d1 = nn.Conv2d(64, 32, kernel_size=1)
        self.d2 = nn.Conv2d(32, 16, kernel_size=1)
        self.d3 = nn.Conv2d(16, 8, kernel_size=1)
        self.fuse = nn.Conv2d(8, 1, kernel_size=1, padding=0, bias=False)
        self.sigmoid = nn.Sigmoid()
        self.cw = nn.Conv2d(2, 1, kernel_size=1, padding=0, bias=False)
        self.expand = nn.Sequential(nn.Conv2d(1, 64, kernel_size=1),
                                    nn.BatchNorm2d(64),
                                    nn.ReLU(inplace=True))

        self.expand1 = nn.Sequential(nn.Conv2d(1, 64, kernel_size=1),
                                     nn.BatchNorm2d(64),
                                     nn.ReLU(inplace=True))
        self.expand2 = nn.Sequential(nn.Conv2d(1, 64, kernel_size=1),
                                     nn.BatchNorm2d(64),
                                     nn.ReLU(inplace=True))
        self.expand3 = nn.Sequential(nn.Conv2d(1, 64, kernel_size=1),
                                     nn.BatchNorm2d(64),
                                     nn.ReLU(inplace=True))

        self.output1 = outconv(64, 1)
        self.output2 = outconv(64, 1)
        self.output3 = outconv(64, 1)
        self.output4 = outconv(64, 1)
        self.up1 = Fusion(64, 64)
        self.up2 = Fusion(64, 64)
        self.up3 = Fusion(64, 64)
        self.outc = outconv(64, 1, dropout=False, rate=0.1)
        self.dsoutc2 = outconv(64, 1)
        self.dsoutc3 = outconv(64, 1)
        self.dsoutc4 = outconv(64, 1)
        self.x41 = BasicConv2d(64, 64, kernel_size=3, padding=1)
        self.x31 = BasicConv2d(64, 64, kernel_size=3, padding=1)
        self.x21 = BasicConv2d(64, 64, kernel_size=3, padding=1)
        self.linearr3 = nn.Conv2d(64, 1, kernel_size=3, stride=1, padding=1)
        self.linearr2 = nn.Conv2d(64, 1, kernel_size=3, stride=1, padding=1)
        self.linearr1 = nn.Conv2d(64, 1, kernel_size=3, stride=1, padding=1)

        self.linearr4 = nn.Conv2d(64, 1, kernel_size=3, stride=1, padding=1)

        self.msa1 = MSCA(64, 4)
        self.msa2 = MSCA(64, 4)
        self.msa3 = MSCA(64, 4)
        #     self.ca = ChannelAttention(64)
        #     self.sa = SpatialAttention()

        # self.down05 = nn.Upsample(scale_factor=0.5, mode='bilinear', align_corners=True)

    #  self.res_bin4 = channel_bind(512,512)
    #  self.res_bin3 = channel_bind(320, 320)
    #  self.res_bin2 = channel_bind(128, 128)
    #  self.res_bin1 = channel_bind(64, 64)
    def forward(self, x):
        inputs = x
        x_size = inputs.size()
        # backbone
        pvt = self.backbone(inputs)
        x1 = pvt[0]
        x2 = pvt[1]
        x3 = pvt[2]
        x4 = pvt[3]

        # edge
        ss = F.interpolate(self.d0(x1), x_size[2:],
                           mode='bilinear', align_corners=True)
        ss = self.res1(ss)
        c3 = F.interpolate(self.c3(x2), x_size[2:],
                           mode='bilinear', align_corners=True)
        ss = self.d1(ss)
        ss1 = self.gate1(ss, c3)
        # print("***********")
        # print(ss1.shape)
        ss = self.res2(ss1)
        ss = self.d2(ss)
        c4 = F.interpolate(self.c4(x3), x_size[2:],
                           mode='bilinear', align_corners=True)
        ss2 = self.gate2(ss, c4)
        ss = self.res3(ss2)
        ss = self.d3(ss)
        c5 = F.interpolate(self.c5(x4), x_size[2:],
                           mode='bilinear', align_corners=True)
        ss3 = self.gate3(ss, c5)
        ss = self.fuse(ss3)
        ss = F.interpolate(ss, x_size[2:], mode='bilinear', align_corners=True)
        edge_out = self.sigmoid(ss)

   #     x1 = self.re_conv1(x1)
   #     x2 = self.re_conv2(x2)
   #     x3 = self.re_conv3(x3)
   #     x4 = self.re_conv4(x4)

        x1f = self.f1(x1)
        x2f = self.f2(x2)
        x3f = self.f3(x3)
        x4f = self.f4(x4)

        edge = self.expand(edge_out)
        edge2 = self.expand2(edge_out)
        edge3 = self.expand3(edge_out)
        edge = F.interpolate(edge, size=x1.size()[2:], mode='bilinear')
        edge2 = F.interpolate(edge2, size=x2.size()[2:], mode='bilinear')
        edge3 = F.interpolate(edge3, size=x3.size()[2:], mode='bilinear')
        #       edge4 = self.expand4(edge_out)

        #      edge4 = F.interpolate(edge4, size=x4f.size()[2:], mode='bilinear')

        #     x41 = self.bca4(x4f, edge4)

        x411 = F.interpolate(x4f, size=x3.size()[2:], mode='bilinear')

        x411 = self.dsoutc4(x411)
        x_41 = -1 * (torch.sigmoid(x411)) + 1
        x_41_weight = x_41.expand(-1, 64, -1, -1)
        x_40_weight = 1 - x_41_weight
        x_40_weight = x_40_weight.mul(x3f)
        x_41_weight = x_41_weight.mul(x3f)
        x_40_weight = self.x41(x_40_weight)
        x_41_weight = self.x41(x_41_weight)
        #   x_4total = x_40_weight + x_41_weight
        #   weight1 = self.msa1(x_4total)
        #  x_map31 = (1-weight1) * x_40_weight
        #  x_map32 = weight1 * x_41_weight
        #  x_map3 = x_map31 + x_map32
        #  x_41_fin = self.bca3(x_map3, edge3)

        x_map3_fin = self.linearr3(x_41_weight)
        x_out3 = F.interpolate(x_map3_fin, x_size[2:], mode='bilinear')

        x31 = F.interpolate(x_41_weight, size=x2.size()[2:], mode='bilinear')

        x31 = self.dsoutc3(x31)
        x_31 = -1 * (torch.sigmoid(x31)) + 1

        x_31_weight = x_31.expand(-1, 64, -1, -1)
        x_30_weight = 1 - x_31_weight
        x_30_weight = x_30_weight.mul(x2f)
        x_31_weight = x_31_weight.mul(x2f)
        x_30_weight = self.x31(x_30_weight)
        x_31_weight = self.x31(x_31_weight)
        #      x_3total = x_30_weight + x_31_weight
        #     weight2 = self.msa2(x_3total)
        #   x_map21 = (1-weight2) * x_30_weight
        #  x_map22 = weight2 * x_31_weight

        #   x_map2 = x_map21 + x_map22
        #   x_31_fin = self.bca2(x_map2, edge2)
        x_map2_fin = self.linearr2(x_31_weight)
        x_out2 = F.interpolate(x_map2_fin, x_size[2:], mode='bilinear')

        x21 = F.interpolate(x_31_weight, size=x1.size()[2:], mode='bilinear')
        x21 = self.dsoutc2(x21)

        x_21 = -1 * (torch.sigmoid(x21)) + 1
        x_21_weight = x_21.expand(-1, 64, -1, -1)
        x_20_weight = 1 - x_21_weight
        x_20_weight = x_20_weight.mul(x1f)
        x_21_weight = x_21_weight.mul(x1f)
        x_20_weight = self.x21(x_20_weight)
        x_21_weight = self.x21(x_21_weight)

        #    x_2total = x_20_weight + x_21_weight
        #    weight3 = self.msa3(x_2total)
        #    x_map11 = (1-weight3) * x_20_weight
        #    x_map12 = weight3 * x_21_weight

        #    x_map1 = x_map11 + x_map12
        #   x_map1 = self.bca1(x_map1, edge)
        x_map1 = self.linearr1(x_21_weight)

        weight1 = self.msa1(x_40_weight + x_41_weight)
        weight2 = self.msa2(x_31_weight + x_30_weight)
        weight3 = self.msa3(x_21_weight + x_20_weight)

        spade4 = x4f
        spade1 = self.bca3(x_41_weight * weight1, edge3)
        spade5 = self.bca3(x_40_weight * (1 - weight1), edge3)
        spade2 = self.bca2(x_31_weight * weight2, edge2)
        spade6 = self.bca2(x_30_weight * (1 - weight2), edge2)
        spade3 = self.bca1(x_21_weight * weight3, edge)
        spade7 = self.bca1(x_20_weight * (1 - weight3), edge)

        SA_4 = spade4
        SA_3 = self.up1(SA_4, spade1 + spade5)
        SA_2 = self.up2(SA_3, spade2 + spade6)
        SA_1 = self.up3(SA_2, spade3 + spade7)

        map4 = self.linearr4(SA_4)
        map4 = F.interpolate(map4, (22, 22), mode='bilinear')
        map3 = self.linearr3(SA_3) + map4
        map3 = F.interpolate(map3, (44, 44), mode='bilinear')
        map2 = self.linearr2(SA_2) + map3
        map2 = F.interpolate(map2, (88, 88), mode='bilinear')
        map1 = self.linearr1(SA_1) + map2

        out_map1 = F.interpolate(map1, size=x_size[2:], mode='bilinear')
        out_map2 = F.interpolate(map2, size=x_size[2:], mode='bilinear')
        out_map3 = F.interpolate(map3, size=x_size[2:], mode='bilinear')
        out_map4 = F.interpolate(map4, size=x_size[2:], mode='bilinear')

        return out_map1, out_map2, out_map3, out_map4, ss


class Fusion(nn.Module):
    def __init__(self, in_ch, out_ch, bilinear=True):
        super(Fusion, self).__init__()

        self.upsample = nn.ConvTranspose2d(in_ch, in_ch, kernel_size=4, stride=2, padding=1)
        self.r1 = ResidualBlock(in_ch + out_ch, out_ch)
        self.r2 = ResidualBlock(out_ch, out_ch)

    def forward(self, x1, x2):
        x1 = self.upsample(x1)
        x = torch.cat([x2, x1], dim=1)
        x = self.r1(x)
        x = self.r2(x)
        #    x = self.p1(x, masks)
        return x


class MSCA(nn.Module):
    def __init__(self, channels=64, r=4):
        super(MSCA, self).__init__()
        out_channels = int(channels // r)
        # local att
        self.local_att = nn.Sequential(
            nn.Conv2d(channels, out_channels, kernel_size=1, stride=1, padding=0),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True),
            nn.Conv2d(out_channels, channels, kernel_size=1, stride=1, padding=0),
            nn.BatchNorm2d(channels)
        )

        # global att
        self.global_att = nn.Sequential(
            nn.AdaptiveAvgPool2d(1),
            nn.Conv2d(channels, out_channels, kernel_size=1, stride=1, padding=0),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True),
            nn.Conv2d(out_channels, channels, kernel_size=1, stride=1, padding=0),
            nn.BatchNorm2d(channels)
        )

        self.sig = nn.Sigmoid()

    def forward(self, x):
        xl = self.local_att(x)
        xg = self.global_att(x)
        xlg = xl + xg
        wei = self.sig(xlg)
        return wei


class ConvBlock(nn.Module):
    def __init__(self, channel, dilation=1):
        super(ConvBlock, self).__init__()

        self.conv = nn.Sequential(
            nn.Conv2d(channel, channel, kernel_size=1),
            nn.BatchNorm2d(channel)
        )
        # 1-d Dilation Conv
        '''
        self.dconv = nn.Sequential(
            nn.Conv2d(channel, channel, kernel_size=3, stride=1, padding=dilation, dilation=dilation, bias=False),
            nn.BatchNorm2d(channel)
        )
        '''
        self.dconv = nn.Sequential(
            nn.Conv2d(channel, channel, kernel_size=(1, 3), stride=1, padding=(0, 1 * dilation), dilation=(1, dilation),
                      bias=False),
            nn.Conv2d(channel, channel, kernel_size=(3, 1), stride=1, padding=(1 * dilation, 0), dilation=(dilation, 1),
                      bias=False),
            nn.BatchNorm2d(channel)
        )

        # Asymmetric conv
        self.asconv = nn.Sequential(
            nn.Conv2d(channel, channel, kernel_size=(1, 3), padding=(0, 1)),
            nn.Conv2d(channel, channel, kernel_size=(3, 1), padding=(1, 0)),
            nn.BatchNorm2d(channel)
        )
        self.out_conv = nn.Sequential(
            nn.Conv2d(channel * 2, channel, kernel_size=1, bias=False),
            nn.BatchNorm2d(channel)
        )

    def forward(self, x):
        x = self.conv(x)
        x = torch.cat((self.dconv(x), self.asconv(x)), dim=1)
        x = self.out_conv(x)
        return x


class DEMS(nn.Module):
    """
    Detail Enhanced Multi-Scale Module
    """

    def __init__(self, channel):
        super(DEMS, self).__init__()
        self.relu = nn.ReLU(True)
        self.branch0 = ConvBlock(channel, dilation=1)
        self.branch1 = ConvBlock(channel, dilation=3)
        self.branch2 = ConvBlock(channel, dilation=5)
        self.branch3 = ConvBlock(channel, dilation=7)
        self.conv_cat = nn.Sequential(
            nn.Conv2d(channel * 3, channel, kernel_size=1),
            nn.BatchNorm2d(channel)
        )

    def forward(self, x):
        x0 = self.branch0(x)
        x1 = self.branch1(x + x0)
        x2 = self.branch2(x + x1)
        x3 = self.branch3(x + x2)
        x_cat = self.conv_cat(torch.cat((x1, x2, x3), dim=1))
        x = self.relu(x0 + x_cat)
        return x


class Conv2D(nn.Module):
    def __init__(self, in_c, out_c, kernel_size=3, padding=1, dilation=1, bias=False, act=True):
        super().__init__()
        self.act = act

        self.conv = nn.Sequential(
            nn.Conv2d(
                in_c, out_c,
                kernel_size=kernel_size,
                padding=padding,
                dilation=dilation,
                bias=bias
            ),
            nn.BatchNorm2d(out_c)
        )
        self.relu = nn.ReLU(inplace=True)

    def forward(self, x):
        x = self.conv(x)
        if self.act == True:
            x = self.relu(x)
        return x


class GatedConv(nn.Conv2d):
    def __init__(self, in_channels, out_channels):
        super().__init__(in_channels, out_channels, 1, bias=False)
        self.attention = nn.Sequential(
            nn.BatchNorm2d(in_channels + 1),
            nn.Conv2d(in_channels + 1, in_channels + 1, 1),
            nn.ReLU(),
            nn.Conv2d(in_channels + 1, 1, 1),
            nn.BatchNorm2d(1),
            nn.Sigmoid()
        )

    def forward(self, feat, gate):
        eatt = feat
        attention = self.attention(torch.cat((feat, gate), dim=1))
        #    score = torch.sigmoid(attention)
        dist = torch.abs(attention - 0.5)
        att = 1 - (dist / 0.5)
        att_x = feat * att
        out = att_x + eatt
        return out


class ConvBnRelu(nn.Module):
    def __init__(self, in_planes, out_planes, ksize, stride, pad, dilation=1,
                 groups=1, has_bn=True, norm_layer=nn.BatchNorm2d,
                 has_relu=True, inplace=True, has_bias=False):
        super(ConvBnRelu, self).__init__()
        self.conv = nn.Conv2d(in_planes, out_planes, kernel_size=ksize,
                              stride=stride, padding=pad,
                              dilation=dilation, groups=groups, bias=has_bias)
        self.has_bn = has_bn
        if self.has_bn:
            self.bn = nn.BatchNorm2d(out_planes)
        self.has_relu = has_relu
        if self.has_relu:
            self.relu = nn.ReLU(inplace=inplace)

    def forward(self, x):
        x = self.conv(x)
        if self.has_bn:
            x = self.bn(x)
        if self.has_relu:
            x = self.relu(x)

        return x


class SELayer(nn.Module):
    def __init__(self, channel, reduction=16):
        super(SELayer, self).__init__()
        self.avg_pool = nn.AdaptiveAvgPool2d(1)
        self.fc = nn.Sequential(
            nn.Linear(channel, channel // reduction, bias=False),
            nn.ReLU(inplace=True),
            nn.Linear(channel // reduction, channel, bias=False),
            nn.Sigmoid()
        )

    def forward(self, x):
        b, c, _, _ = x.size()
        y = self.avg_pool(x).view(b, c)
        y = self.fc(y).view(b, c, 1, 1)
        return x * y.expand_as(x)


""" 3x3->3x3 Residual block """


class ResidualBlock(nn.Module):
    def __init__(self, in_c, out_c):
        super(ResidualBlock, self).__init__()

        self.conv1 = nn.Conv2d(in_c, out_c, kernel_size=3, padding=1)
        self.bn1 = nn.BatchNorm2d(out_c)

        self.conv2 = nn.Conv2d(out_c, out_c, kernel_size=3, padding=1)
        self.bn2 = nn.BatchNorm2d(out_c)

        self.conv3 = nn.Conv2d(in_c, out_c, kernel_size=1, padding=0)
        self.bn3 = nn.BatchNorm2d(out_c)

        self.se = SELayer(out_c, out_c)
        self.relu = nn.LeakyReLU(0.2, inplace=True)

    def forward(self, x):
        x1 = self.conv1(x)
        x1 = self.bn1(x1)
        x1 = self.relu(x1)

        x2 = self.conv2(x1)
        x2 = self.bn2(x2)

        x3 = self.conv3(x)
        x3 = self.bn3(x3)
        x3 = self.se(x3)

        x4 = x2 + x3
        x4 = self.relu(x4)

        return x4


from thop import profile

if __name__ == '__main__':
    model = PolypPVT().cuda()
    # stat(model, (3, 416, 416))

    dummy_input = torch.randn(1, 3, 352, 352).cuda()
    flops, params = profile(model, (dummy_input,))
    print('flops: ', flops, 'params: ', params)
    print('flops: %.2f M, params: %.2f M' % (flops / 1000000.0, params / 1000000.0))
