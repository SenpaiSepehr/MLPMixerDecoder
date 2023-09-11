# -*- coding: utf-8 -*-
"""MLPMixer

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1FbM2avr6fIsMMAZZlxj-q3jHR0rLMZhj
"""

!pip install einops
!pip install torchinfo

import torch
from torch import nn
from functools import partial
import torch.nn.functional as F
from einops.layers.torch import Rearrange, Reduce

class FC(nn.Module):
  def __init__(self, input_dim, output_dim):
    super().__init__()
    self.proj = nn.Linear(input_dim, output_dim)

  def forward(self,x):
    x = x.flatten(2).transpose(1,2) #flatten along w,h then swap with channels
    x = self.proj(x) # reduce channels to 256
    return x

linear4 = FC(input_dim = 512, output_dim = 256)
linear3 = FC(input_dim = 320, output_dim = 256)

def resize(input, size=None, scale_factor=None, mode='nearest', align_corners=None, warning=True):
    if warning:
        if size is not None and align_corners:
            input_h, input_w = tuple(int(x) for x in input.shape[2:])
            output_h, output_w = tuple(int(x) for x in size)

            if output_h > input_h or output_w > output_h:

                if ((output_h > 1 and output_w > 1 and input_h > 1
                     and input_w > 1) and (output_h - 1) % (input_h - 1)
                        and (output_w - 1) % (input_w - 1)):

                    warnings.warn(
                        f'When align_corners={align_corners}, '
                        'the output would more aligned if '
                        f'input size {(input_h, input_w)} is `x+1` and '
                        f'out size {(output_h, output_w)} is `nx+1`')
    return F.interpolate(input, size, scale_factor, mode, align_corners)

linear_fuse = nn.Sequential(
    nn.Conv2d(in_channels = 512, out_channels = 256, kernel_size = 1),
    nn.BatchNorm2d(256)
)

class UpsampleConvLayer(torch.nn.Module):
    def __init__(self, in_channels, out_channels, kernel_size, stride):
        super(UpsampleConvLayer, self).__init__()
        self.conv2d = nn.ConvTranspose2d(in_channels, out_channels, kernel_size, stride=stride, padding=1)

    def forward(self, x):
        out = self.conv2d(x)
        return out

pair = lambda x: x if isinstance(x, tuple) else (x, x)

class PreNormResidual(nn.Module):
    def __init__(self, dim, fn):
        super().__init__()
        self.fn = fn
        self.norm = nn.LayerNorm(dim)

    def forward(self, x):
        x = self.fn(self.norm(x)) + x
        return x

def FeedForward(dim, expansion_factor = 4, dropout = 0., dense = nn.Linear):
    inner_dim = int(dim * expansion_factor)
    return nn.Sequential(
        dense(dim, inner_dim),
        nn.GELU(),
        nn.Dropout(dropout),
        dense(inner_dim, dim),
        nn.Dropout(dropout)
    )

def MLPMixer(*, image_size, channels, patch_size, dim, depth, expansion_factor = 1, expansion_factor_token = 0.5, dropout = 0.):
    image_h, image_w = pair(image_size)
    assert (image_h % patch_size) == 0 and (image_w % patch_size) == 0, 'image must be divisible by patch size'
    num_patches = (image_h // patch_size) * (image_w // patch_size) #4
    chan_first, chan_last = partial(nn.Conv1d, kernel_size = 1), nn.Linear

    input_dim = (patch_size ** 2) * channels
    h = image_h // patch_size
    w = image_w // patch_size

    return nn.Sequential(
        Rearrange('b c (h p1) (w p2) -> b (h w) (p1 p2 c)', p1 = patch_size, p2 = patch_size), #(8,512,2*4,2*4) -> (8,2*2,4*4*512)
        nn.Linear(input_dim, dim), # input (768) -> 512
        *[nn.Sequential(
            PreNormResidual(dim, FeedForward(dim, expansion_factor_token, dropout, chan_last)),   #(512,FeedFWD(512,0.5,0.,nn.Linear)), (8,4,512)
            PreNormResidual(dim, FeedForward(num_patches, expansion_factor, dropout, chan_first)) #(512,FeedFWD(4,4,0,conv1d))
        ) for _ in range(depth)],
        nn.LayerNorm(dim),
        nn.Linear(dim,input_dim), # 512 -> input
        Rearrange('b (h w) (p1 p2 c) -> b c (h p1) (w p2)', h = h, w = w,
                  p2 = patch_size, p1 = patch_size)
    )

model = MLPMixer(
    image_size = (224,224),
    channels = 3,
    patch_size = 32,
    dim = 512,
    depth = 8,
    )

model0 = MLPMixer(
    image_size = (224,224),
    channels = 3,
    patch_size = 56,
    dim = 512,
    depth = 1,
    )

model1 = MLPMixer(
    image_size = (8,8),
    channels = 512,
    patch_size = 2,
    dim = 512,
    depth = 1,
    )

model2 = MLPMixer(
    image_size = (16,16),
    channels = 320,
    patch_size = 4,
    dim = 512,
    depth = 1,
    )

from torchinfo import summary
summary(model0,(1,3,224,224), col_names = ["output_size","num_params",
                                                                    "params_percent"])

summary(model1,(1,512,8,8), col_names = ["output_size","num_params","params_percent"])

summary(model2,(1,320,16,16), col_names = ["output_size","num_params","params_percent"])

# # feat3 feat 4 are difference features
# feat4 = torch.randn(8,512,8,8)
# feat3 = torch.randn(8,320,16,16)
# feat2 = torch.randn(8,64,64,64)

### send to mixer
# mlp4 = model1(feat4)  #(8,512,8,8)
# mlp3 = model2(feat3)  #(8,320,16,16)


# ### Flatten and Reshape to unify Channels -> 256
# shaped4 = linear4(mlp4).permute(0,2,1).reshape(8,-1,8,8)
# shaped3 = linear3(mlp3).permute(0,2,1).reshape(8,-1,16,16)


# ### Reshape and Match in H, W -> (64x64)
# resize4 = resize(shaped4, size=feat2.size()[2:], mode = 'bilinear', align_corners=False)
# resize3 = resize(shaped3, size = feat2.size()[2:], mode = 'bilinear', align_corners=False)

# # fuse feat4 feat3, cat along channel dim
# fuse_feat = linear_fuse(torch.cat([resize4,resize3], dim=1))  # (8,256,64,64)

# Upsample by x4 -> (8,256,256,256)

# send to prediction head for logits