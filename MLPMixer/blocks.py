import torch
import torch.nn as nn
import torch.nn.functional as F

import einops

class MLPUnit(nn.Module):
    def __init__(self, in_out_dim, mlp_dim=None):
        super(MLPUnit, self).__init__()
        
        self.in_out_dim = in_out_dim
        self.mlp_dim = mlp_dim
        
        if not self.mlp_dim:
            self.mlp_dim = self.in_out_dim
        
        self.fc1 = nn.Linear(self.in_out_dim, self.mlp_dim)
        self.gelu = nn.GELU()
        self.fc2 = nn.Linear(self.mlp_dim, self.in_out_dim)
        
    def forward(self, x):
        return self.fc2(self.gelu(self.fc1(x)))
    
class MixerUnit(nn.Module):
    def __init__(self, nb_tokens, nb_channels, token_mlp_dim, channel_mlp_dim):
        super(MixerUnit, self).__init__()
        
        self.nb_tokens = nb_tokens
        self.nb_channels = nb_channels
        self.token_mlp_dim = token_mlp_dim
        self.channel_mlp_dim = channel_mlp_dim
        
        self.ln1 = nn.LayerNorm(self.nb_channels)
        self.ln2 = nn.LayerNorm(self.nb_channels)
        
        self.token_mixer = MLPUnit(self.nb_tokens, self.token_mlp_dim)
        self.channel_mixer = MLPUnit(self.nb_channels, self.channel_mlp_dim)
        
    def forward(self, x):
        # Apply layer norm, swap dims `1, 2` and send it to token mixer
        y = self.ln1(x)
        y = y.permute(0, 2, 1)
        y = self.token_mixer(y)
        
        # Change the dimensions back to what they were before
        y = y.permute(0, 2, 1)
        
        # Add the original x (Skip Connection) with output from token mixer
        x = x + y
        
        # Apply layer norm again but this time just send directly to the channel mixer
        y = self.ln2(x)
        out = self.channel_mixer(y)
        
        # Return the output from the channel mixer added with original x (another Skip Connection)
        return x + out
    
class MLPMixer(nn.Module):
    def __init__(
        self, 
        image_size,
        patch_size,
        tokens_mlp_dim,
        channels_mlp_dim,
        total_classes,
        total_channels,
        total_blocks
        ):
        
        super(MLPMixer, self).__init__()
        self.image_size = image_size
        self.patch_size = patch_size
        self.tokens_mlp_dim = tokens_mlp_dim
        self.channels_mlp_dim = channels_mlp_dim
        self.total_classes = total_classes
        self.total_channels = total_channels
        self.total_blocks = total_blocks
        
        assert self.image_size // self.patch_size, \
            "An integral number of patches should be formed from the image"
            
        total_tokens = (self.image_size // self.patch_size) ** 2
        
        self.patch_to_embedding = nn.Conv2d(
            3, 
            self.total_channels, 
            kernel_size=self.patch_size, 
            stride=self.patch_size
        )
        
        self.mixer_blocks = []
        for i in range(self.total_blocks):
            self.mixer_blocks.append(MixerUnit(
                nb_tokens=total_tokens,
                nb_channels=self.total_channels,
                token_mlp_dim=self.tokens_mlp_dim,
                channel_mlp_dim=self.channels_mlp_dim
            ))
        
        self.norm = nn.LayerNorm(self.total_channels)
        self.head = nn.Linear(self.total_channels, self.total_classes)
        
    def forward(self, x):
        out = self.patch_to_embedding(x)
        out = einops.rearrange(out, 'n c h w -> n (h w) c')
        
        for mixer in self.mixer_blocks:
            out = mixer(out)
        
        out = self.norm(out)
        out = out.mean(dim=1) # Global average pooling
        out = self.head(out)
        
        return out