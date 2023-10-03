import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision.models import resnet50

def get_ResNet():
    """获得主干网络ResNet50"""
    model = resnet50(pretrained=True)
    # 设置模型的输出通道,fc为ResNet中的最后一层，它的in_features即为输出的类别，就是输出通道，为2048
    output_channels = model.fc.in_features
    model = list(model.children())[:-2]
    return model, output_channels

class RAm(nn.Module):
    "Rich Attention module"
    def __init__(self, output_channels, M) -> None:
        super().__init__()
        self.M = M
        self.output_channels = output_channels
        self.attention_generate_layer = nn.Sequential(
            nn.Conv2d(output_channels, M, kernel_size=1),
            nn.ReLU()
        )
        self.diversity = nn.Linear(output_channels, M)
        self.GAP = nn.AdaptiveAvgPool2d(1)

    def generate_vector(self, atten_map, feature_map):
        return torch.squeeze(F.adaptive_avg_pool2d(atten_map*feature_map, 1))

    def forward(self, feature_map):
        attn_map = self.attention_generate_layer(feature_map)
        v = torch.zeros([attn_map.shape[0], self.M, self.output_channels], device=attn_map.device)
        for i in range(self.M):
            # v[:,i] = self.generate_vector(attn_map[:, i].unsqueeze(dim=1), feature_map)
            v[:,i] = torch.squeeze(self.GAP(attn_map[:, i].unsqueeze(dim=1)*feature_map))
        P = torch.zeros([feature_map.shape[0], self.M, self.M], device=v.device)
        for i in range(self.M):
            P[:, i] = self.diversity(v[:, i])

        return P, v

class RA_Net(nn.Module):
    "Rich Attention Net"
    def __init__(self, backbone, output_channels, M) -> None:
        super().__init__()
        self.output_channels = output_channels
        self.M = M
        self.backbone = nn.Sequential(*backbone)
        self.RAm = RAm(output_channels, M)
        self.GAP = nn.AdaptiveAvgPool2d(1)
        self.classifer = nn.Sequential(
            nn.Linear(output_channels, 1024),
            nn.BatchNorm1d(1024),
            nn.ReLU(),
            nn.Linear(1024, 512),
            nn.BatchNorm1d(512),
            nn.ReLU(),
            nn.Linear(512, 1)
        )

    def forward(self, image, ifTest):
        feature_map = self.backbone(image)

        x = self.GAP(feature_map)
        x = torch.squeeze(x)
        x = x.view(-1, self.output_channels)
        y_hat = self.classifer(x)
        # return y_hat, 0, 0
        # if ifTest:
        #     return y_hat

        P, v = self.RAm(feature_map)
        y_RA = torch.zeros([v.shape[0], self.M], device=v.device)
        for i in range(self.M):
            y_RA[:, i] = torch.squeeze(self.classifer(v[:, i]))
        return y_hat, y_RA, P

    # 加入微调函数
    def fine_tune(self, need_fine_tune = True):
        self.train(need_fine_tune)

class myres(nn.Module):
    """主模型MMANet的在输入到GA前的部分"""
    # 不在类内定义主干网络是因为怕梯度损失吗
    def __init__(self, backbone, out_channels) -> None:
        super().__init__()
        
        self.out_channels = out_channels
        self.backbone = nn.Sequential(*backbone)
        
        self.FC0 = nn.Linear(out_channels, 1024)
        self.BN0 = nn.BatchNorm1d(1024)

        self.FC1 = nn.Linear(1024, 512)
        self.BN1 = nn.BatchNorm1d(512)

        self.output = nn.Linear(512, 1)
        # self.output = nn.Linear(512, 240)

    def forward(self, image):

        x = self.backbone(image)

        x = F.adaptive_avg_pool2d(x, 1) # N(2048)(H/32)(W/32) -> N(2048)(1)(1)

        x = torch.squeeze(x)

        x = x.view(-1, self.out_channels)

        x = F.relu(self.BN0(self.FC0(x)))
        x = F.relu(self.BN1(self.FC1(x)))
        output_beforeGA = self.output(x)

        return output_beforeGA
    
    def fine_tune(self, need_fine_tune = True):
        self.train(need_fine_tune)


if __name__ == '__main__':
    x = torch.ones([10, 3, 512, 512], dtype=torch.float32)
    x = x.cuda()
    M = 4
    net = RA_Net(*get_ResNet(), M).cuda()
    net.fine_tune()
    y_hat, y_RA, P = net(x, False)

    print(f"y_hat is :\n{y_hat}\ny_RA is :\n{y_RA}\nP is :\n{P}")
