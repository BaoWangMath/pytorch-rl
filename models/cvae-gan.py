import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
from torch.autograd import Variable
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader

USE_CUDA = torch.cuda.is_available()


class Encoder(nn.Module):

    """
    The encoder network in the cvae-gan pipeline

    Given an image, this network returns the latent encoding
    for the image.

    """

    def __init__(self, conv_layers, conv_kernel_size,
                 latent_space_dim, hidden_dim, use_cuda,
                 height, width, input_channels,pool_kernel_size):
        super(Encoder, self).__init__()

        self.conv_layers = conv_layers
        self.conv_kernel_size = conv_kernel_size
        self.z_dim = latent_space_dim
        self.hidden_dim = hidden_dim
        self.use_cuda = use_cuda
        self.height = height
        self.width = width
        self.in_channels = input_channels
        self.pool_size = pool_kernel_size

        # Encoder Architecture

        # 1st Stage
        self.conv1 = nn.Conv2d(in_channels=self.in_channels, out_channels=self.conv_layers,
                               kernel_size=self.conv_kernel_size)
        self.conv2 = nn.Conv2d(in_channels=self.conv_layers, out_channels=self.conv_layers,
                               kernel_size=self.conv_kernel_size)
        self.pool = nn.MaxPool2d(kernel_size=pool_kernel_size)

        # 2nd Stage
        self.conv3 = nn.Conv2d(in_channels=self.conv_layers, out_channels=self.conv_layers*2,
                               kernel_size=self.conv_kernel_size)
        self.conv4 = nn.Conv2d(in_channels=self.conv_layers*2, out_channels=self.conv_layers*2,
                               kernel_size=self.conv_kernel_size)
        self.pool2  = nn.MaxPool2d(kernel_size=pool_kernel_size)

        # Linear Layer
        self.linear1 = nn.Linear(in_features=self.height//4*self.width//4*self.conv_layers*2, out_features=self.hidden_dim)
        self.latent_mu = nn.Linear(in_features=self.hidden, out_features=self.z_dimension)
        self.latent_logvar = nn.Linear(in_features=self.hidden, out_features=self.z_dimension)
        self.relu = nn.ReLU(inplace=True)


    def encode(self, x):
        # Encoding the input image to the mean and var of the latent distribution
        bs, _, _, _ = x.shape

        conv1 = self.conv1(x)
        conv1 = self.relu(conv1)
        conv2 = self.conv2(conv1)
        conv2 = self.relu(conv2)
        pool = self.pool(conv2)

        conv3 = self.conv3(pool)
        conv3 = self.relu(conv3)
        conv4 = self.conv4(conv3)
        conv4 = self.relu(conv4)
        pool2 = self.pool2(conv4)

        pool2 = pool2.view((bs, -1))

        linear = self.linear1(pool2)
        linear = self.relu(linear)
        mu = self.latent_mu(linear)
        logvar = self.latent_logvar(linear)

        return mu, logvar

    def reparameterize(self, mu, logvar):
        # Reparameterization trick as shown in the auto encoding variational bayes paper
        if self.training:
            std = logvar.mul(0.5).exp_()
            eps = Variable(std.data.new(std.size()).normal_())
            return eps.mul(std).add_(mu)
        else:
            return mu

    def forward(self, input):
        mu, logvar = self.encode(input)
        z = self.reparameterize(mu, logvar)
        return z, mu, logvar


class Generator(nn.Module):

    """
    The generator/decoder in the CVAE-GAN pipeline

    Given a latent encoding or a noise vector, this network outputs an image.

    """

    def __init__(self, latent_space_dimension, conv_kernel_size,
                 conv_layers, hidden_dim, height, width, input_channels):
        super(Generator, self).__init__()

        self.z_dimension = latent_space_dimension
        self.conv_layers = conv_layers
        self.conv_kernel_size = conv_kernel_size
        self.hidden = hidden_dim
        self.height = height
        self.width = width
        self.input_channels = input_channels

        # Decoder/Generator Architecture
        self.linear_decoder = nn.Linear(in_features=self.z_dimension,
                                        out_features=self.hidden)
        self.linear_decoder1 = nn.Linear(in_features=self.hidden,
                                         out_features=self.height//4 * self.width//4 * self.conv_layers*2)

        # Deconvolution layers
        self.conv1 = nn.ConvTranspose2d(in_channels=self.height//4 * self.width//4 * self.conv_layers*2,
                                        out_channels=self.conv_layers*2, kernel_size=self.conv_kernel_size,
                                        stride=2)
        self.conv2 = nn.Conv2d(in_channels=self.conv_layers*2, out_channels=self.conv_layers*2,
                               kernel_size=self.conv_kernel_size)
        self.conv3 = nn.ConvTranspose2d(in_channels=self.conv_layers*2, out_channels=self.conv_layers,
                                        kernel_size=self.conv_kernel_size, stride=2)
        self.conv4 = nn.Conv2d(in_channels=self.conv_layers, out_channels=self.conv_layers,
                               kernel_size=self.conv_kernel_size)

        self.output = nn.Conv2d(in_channels=self.conv_layers, out_channels=self.input_channels,
                                kernel_size=self.conv_kernel_size-1)

        self.relu = nn.ReLU(inplace=True)


    def forward(self, z):
        z  = self.linear_decoder(z)
        z = self.relu(z)
        z = self.linear_decoder1(z)
        z = self.relu(z)

        z =  z.view((-1, self.conv_layers*2, self.height//4, self.width//4))

        z = self.conv1(z)
        z = self.relu(z)
        z = self.conv2(z)
        z = self.relu(z)

        z = self.conv3(z)
        z = self.relu(z)
        z = self.conv4(z)
        z = self.relu(z)

        output = self.output(z)

        return output


class Discriminator(nn.Module):

    """
    The discriminator network in the CVAEGAN pipeline

    This network distinguishes the fake images from the real

    """

    def __init__(self, input_channels, conv_layers,
                 pool_kernel_size, conv_kernel_size,
                 height, width, hidden):

        super(Discriminator, self).__init__()

        self.in_channels = input_channels
        self.conv_layers = conv_layers
        self.pool = pool_kernel_size
        self.conv_kernel_size = conv_kernel_size
        self.height = height
        self.width = width
        self.hidden = hidden

        # Discriminator architecture
        self.conv1 = nn.Conv2d(in_channels=self.in_channels, out_channels=self.conv_layers,
                               kernel_size=self.conv_kernel_size)
        self.conv2 = nn.Conv2d(in_channels=self.conv_layers, out_channels=self.conv_layers,
                               kernel_size=self.conv_kernel_size)
        self.pool_1 = nn.MaxPool2d(kernel_size=self.pool)

        self.conv3 = nn.Conv2d(in_channels=self.conv_layers, out_channels=self.conv_layers*2,
                               kernel_size=self.conv_kernel_size)
        self.conv4 = nn.Conv2d(in_channels=self.conv_layers*2, out_channels=self.conv_layers*2,
                               kernel_size=self.conv_kernel_size)
        self.pool_2 = nn.MaxPool2d(kernel_size=self.pool)

        self.relu = nn.ReLU(inplace=True)

        # Fully Connected Layer
        self.hidden_layer1 = nn.Linear(in_features=self.height//4*self.width//4*self.conv_layers*2,
                                       out_features=self.hidden)
        self.output = nn.Linear(in_features=self.hidden, out_features=1)
        self.sigmoid_output = nn.Sigmoid()

    def forward(self, input):

        conv1 = self.conv1(input)
        conv1 = self.relu(conv1)
        conv2 = self.conv2(conv1)
        conv2 = self.relu(conv2)
        pool1 = self.pool_1(conv2)

        conv3 = self.conv3(pool1)
        conv3 = self.relu(conv3)
        conv4 = self.conv2(conv3)
        conv4 = self.relu(conv4)
        pool2 = self.pool_2(conv4)

        pool2 = pool2.view((-1, self.height//4*self.width//4*self.conv_layers*2))

        hidden = self.hidden_layer1(pool2)
        hidden = self.relu(hidden)

        feature_mean = hidden

        output = self.output(hidden)
        output = self.sigmoid_output(output)

        return output, feature_mean


class CVAEGAN(object):

    """

    The complete CVAEGAN Class containing the following models

    1. Encoder
    2. Generator/Decoder
    3. Discriminator

    """

    def __init__(self, encoder,
                 batch_size,
                 num_epochs,
                 random_seed, dataset,
                 generator, discriminator,
                 encoder_lr, generator_lr,
                 discriminator_lr, use_cuda,
                 encoder_weights=None, generator_weights=None,
                 shuffle=True,
                 discriminator_weights=None):

        self.encoder = encoder
        self.generator = generator
        self.discriminator = discriminator

        self.shuffle = shuffle
        self.dataset = dataset
        self.e_lr = encoder_lr
        self.g_lr = generator_lr
        self.d_lr = discriminator_lr
        self.seed = random_seed
        self.batch = batch_size
        self.num_epochs = num_epochs

        self.e_optim = optim.Adam(lr=self.e_lr, params=self.encoder.parameters())
        self.g_optim = optim.Adam(lr=self.g_lr, params=self.generator.parameters())
        self.d_optim = optim.Adam(lr=self.d_lr, params=self.discriminator.parameters())

        self.encoder_weights = encoder_weights
        self.generator_weights = generator_weights
        self.discriminator_weights = discriminator_weights
        self.use_cuda = use_cuda

        if use_cuda:
            self.encoder = self.encoder.cuda()
            self.generator = self.generator.cuda()
            self.discriminator = self.discriminator.cuda()

    def set_seed(self):
        np.random.seed(self.seed)


    def get_dataloader(self):
        # Generates the dataloader for the images for training

        dataset_loader = DataLoader(self.dataset,
                                    batch_size=self.batch,
                                    shuffle=self.shuffle)

        return dataset_loader

    def save_model(self, output, model):
        """
        Saving the models
        :param output:
        :return:
        """
        print("Saving the cvaegan model")
        torch.save(
            model.state_dict(),
            '{}/cvaegan.pt'.format(output)
        )

    def load_model(self):
        # Load the model from the saved weights file
        if self.encoder_weights is not None:
            model_state_dict = torch.load(self.encoder_weights)
            self.encoder.load_state_dict(model_state_dict)

        if self.generator_weights is not None:
            model_state_dict = torch.load(self.generator_weights)
            self.generator.load_state_dict(model_state_dict)

        if self.discriminator_weights is not None:
            model_state_dict = torch.load(self.discriminator_weights)
            self.discriminator.load_state_dict(model_state_dict)


    def klloss(self, mu, logvar):

        mu_sum_sq = (mu*mu).sum(dim=1)
        sigma = logvar.mul(0.5).exp_()
        sig_sum_sq = (sigma * sigma).sum(dim=1)
        log_term = (1 + torch.log(sigma ** 2)).sum(dim=1)
        kldiv = -0.5 * (log_term - mu_sum_sq - sig_sum_sq)

        return kldiv.mean()

    def discriminator_loss(self, x, recon_x, recon_x_noise):
        loss_real = nn.NLLLoss()(torch.ones_like(x), x)
        loss_fake = nn.NLLLoss()(torch.zeros_like(recon_x), recon_x)
        loss_fake_noise = nn.NLLLoss()(torch.zeros_like(recon_x_noise), recon_x_noise)
        loss = torch.mean(loss_fake+loss_fake_noise+loss_real)
        return loss

    def generator_discriminator_loss(self, x,
                                     recon_x_noise, recon_x,
                                     lambda_1, lambda_2):

        # Generator Discriminator loss
        _, fd_x = self.discriminator(x)
        _, fd_x_noise = self.discriminator(recon_x_noise)

        fd_x = torch.mean(fd_x)
        fd_x_noise = torch.mean(fd_x_noise)

        loss_g_d = nn.MSELoss()(fd_x, fd_x_noise)


        # Generator Loss
        reconstruction_loss = nn.MSELoss()(recon_x, x)
        _, fd_x_r = self.discriminator(x)
        _, fd_x_f = self.discriminator(recon_x)
        feature_matching_reconstruction_loss = nn.MSELoss()(fd_x_f, fd_x_r)

        loss_g = reconstruction_loss + feature_matching_reconstruction_loss

        loss = lambda_1*loss_g_d +  lambda_2*loss_g

        return loss, loss_g, loss_g_d

    def sample_random_noise(self, z):
        noise = Variable(torch.randn(z.shape))
        if self.use_cuda:
            noise = noise.cuda()
        return noise

    def train(self, lambda_1, lambda_2):

        for epoch in range(self.num_epochs):
            cummulative_loss_enocder = 0
            cummulative_loss_discriminator = 0
            cummulative_loss_generator = 0
            for i_batch, sampled_batch in enumerate(self.get_dataloader()):
                images = sampled_batch['image']
                images = Variable(images)
                if self.use_cuda:
                    images = images.cuda()


                latent_vectors, mus, logvars = self.encoder(images)
                loss_kl = self.klloss(mus, logvar=logvars)

                # Reconstruct images from latent vectors - x_f
                recon_images = self.generator(latent_vectors)

                # Reconstruct images from random noise - x_p
                random_noise = self.sample_random_noise(latent_vectors)
                recon_images_noise = self.generator(random_noise)

                self.d_optim.zero_grad()

                # Discriminator Loss
                loss_d = self.discriminator_loss(x=images, recon_x=recon_images, recon_x_noise=recon_images_noise)

                cummulative_loss_discriminator += loss_d

                self.g_optim.zero_grad()

                # Generator Loss
                loss_g, l_g, l_g_d = self.generator_discriminator_loss(x=images, recon_x_noise=recon_images_noise,
                                                           recon_x=recon_images, lambda_1=1e-3, lambda_2=1)

                cummulative_loss_generator += loss_g

                self.e_optim.zero_grad()

                # Encoder Loss
                loss_e = lambda_1*loss_kl + lambda_2*l_g

                cummulative_loss_enocder += loss_e

                # Make the gradient updates

                loss_d.backward()
                self.d_optim.step()

                loss_g.backward()
                self.g_optim.step()

                loss_e.backward()
                self.e_optim.step()

            print('Loss Encoder ', cummulative_loss_enocder)
            print('Loss Generator ', cummulative_loss_generator)
            print('Loss Discriminator ', cummulative_loss_discriminator)