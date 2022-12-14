import argparse
from model import Generator
from torch.autograd import Variable
import torch
import torch.nn.functional as F
import numpy as np
import os
from os.path import join, basename, dirname, split
import time
import datetime
from data_loader import to_categorical
import librosa
from utils import *
import glob
import soundfile as sf
import io
from six.moves.urllib.request import urlopen
# Below is the accent info for the used 10 speakers.
spk2acc = {'262': 'Edinburgh',  # F
           '272': 'Edinburgh',  # M
           '229': 'SouthEngland',  # F
           '232': 'SouthEngland',  # M
           '292': 'NorthernIrishBelfast',  # M
           '293': 'NorthernIrishBelfast',  # F
           '360': 'AmericanNewJersey',  # M
           '361': 'AmericanNewJersey',  # F
           '248': 'India',  # F
           '251': 'India'}  # M

speakers = ['chest', 'falset']  # MODIFY
spk2idx = dict(zip(speakers, range(len(speakers))))


class TestDataset(object):
    """Dataset for testing."""

    def __init__(self, config):
        assert config.trg_spk in speakers, f'The trg_spk should be chosen from {speakers}, but you choose {trg_spk}.'
        # Source speaker
        self.src_spk = config.src_spk
        self.trg_spk = config.trg_spk

        self.mc_files = sorted(
            glob.glob(join(config.test_data_dir, f'*_{config.src_spk}_*.npy')))
        print(self.mc_files)
        self.src_spk_stats = np.load(
            join(config.train_data_dir, f'{config.src_spk}_stats.npz'))
        self.src_wav_dir = f'{config.wav_dir}/{config.src_spk}'

        self.trg_spk_stats = np.load(
            join(config.train_data_dir, f'{config.trg_spk}_stats.npz'))

        self.logf0s_mean_src = self.src_spk_stats['log_f0s_mean']
        self.logf0s_std_src = self.src_spk_stats['log_f0s_std']
        self.logf0s_mean_trg = self.trg_spk_stats['log_f0s_mean']
        self.logf0s_std_trg = self.trg_spk_stats['log_f0s_std']
        self.feat_mean_src = self.src_spk_stats['coded_sps_mean']
        self.feat_std_src = self.src_spk_stats['coded_sps_std']
        self.feat_mean_trg = self.trg_spk_stats['coded_sps_mean']
        self.feat_std_trg = self.trg_spk_stats['coded_sps_std']

        self.spk_idx_trg = spk2idx[config.trg_spk]
        self.spk_idx_src = spk2idx[config.src_spk]
        spk_cat_trg = to_categorical(
            [self.spk_idx_trg], num_classes=len(speakers))
        spk_cat_src = to_categorical(
            [self.spk_idx_src], num_classes=len(speakers))
        self.spk_c_trg = spk_cat_trg
        self.spk_c_src = spk_cat_src
        self.spk_c_mix = spk_cat_trg*1

    def get_batch_test_data(self, batch_size=4):
        batch_data = []
        for i in range(batch_size):
            mcfile = self.mc_files[i]
            filename = basename(mcfile).split('-')[-1]
            wavfile_path = join(
                self.src_wav_dir, filename.replace('npy', 'wav'))
            batch_data.append(wavfile_path)
        return batch_data


def load_wav(wavfile, sr=16000):
    wav, _ = librosa.load(wavfile, sr=sr, mono=True)
    return wav_padding(wav, sr=sr, frame_period=5, multiple=4)  # TODO
    # return wav


def load_wav_url(wav_url):
    wav, sr = sf.read(io.BytesIO(urlopen(wav_url).read()))
    print(sr)
    wav_r = librosa.resample(wav, orig_sr=sr, target_sr=16000)
    return wav_padding(wav_r, sr=sr, frame_period=5, multiple=4)  # TODO


def test(config):
    if config.use_url == False:
        os.makedirs(join(config.convert_dir, str(
            config.resume_iters)), exist_ok=True)
        sampling_rate, num_mcep, frame_period = 16000, 36, 5
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

        G = Generator().to(device)
        test_loader = TestDataset(config)
        # Restore model
        print(f'Loading the trained models from step {config.resume_iters}...')
        G_path = join(config.model_save_dir, f'{config.resume_iters}-G.ckpt')
        G.load_state_dict(torch.load(
            G_path, map_location=lambda storage, loc: storage))

        # Read a batch of testdata
        test_wavfiles = test_loader.get_batch_test_data(
            batch_size=config.num_converted_wavs)
        test_wavs = [load_wav(wavfile, sampling_rate)
                     for wavfile in test_wavfiles]
        with torch.no_grad():
            for idx, wav in enumerate(test_wavs):
                print(len(wav))
                wav_name = basename(test_wavfiles[idx])
                # print(wav_name)
                f0, timeaxis, sp, ap = world_decompose(
                    wav=wav, fs=sampling_rate, frame_period=frame_period)
                f0_converted = pitch_conversion(f0=f0,
                                                mean_log_src=test_loader.logf0s_mean_src, std_log_src=test_loader.logf0s_std_src,
                                                mean_log_target=test_loader.logf0s_mean_trg, std_log_target=test_loader.logf0s_std_trg)
                coded_sp = world_encode_spectral_envelop(
                    sp=sp, fs=sampling_rate, dim=num_mcep)

                print("Before being fed into G: ", coded_sp.shape)
                coded_sp_norm = (coded_sp - test_loader.mcep_mean_src) / \
                    test_loader.mcep_std_src
                coded_sp_norm_tensor = torch.FloatTensor(
                    coded_sp_norm.T).unsqueeze_(0).unsqueeze_(1).to(device)
                spk_conds = torch.FloatTensor(test_loader.spk_c_trg).to(device)
                # print(spk_conds.size())
                coded_sp_converted_norm = G(
                    coded_sp_norm_tensor, spk_conds).data.cpu().numpy()
                coded_sp_converted = np.squeeze(
                    coded_sp_converted_norm).T * test_loader.mcep_std_trg + test_loader.mcep_mean_trg
                coded_sp_converted = np.ascontiguousarray(coded_sp_converted)
                print("After being fed into G: ", coded_sp_converted.shape)
                wav_transformed = world_speech_synthesis(f0=f0_converted, coded_sp=coded_sp_converted,
                                                         ap=ap, fs=sampling_rate, frame_period=frame_period)
                wav_id = wav_name.split('.')[0]
                sf.write(join(config.convert_dir, str(config.resume_iters),
                              f'{wav_id}-vcto-{test_loader.trg_spk}.wav'), wav_transformed, sampling_rate)
                if [True, False][0]:
                    wav_cpsyn = world_speech_synthesis(f0=f0, coded_sp=coded_sp,
                                                       ap=ap, fs=sampling_rate, frame_period=frame_period)
                    sf.write(join(config.convert_dir, str(config.resume_iters),
                                  f'cpsyn-{wav_name}'), wav_cpsyn, sampling_rate)
    else:
        # load wav
        sampling_rate, num_mcep, frame_period = 16000, 56, 5
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        wav, sr = sf.read(config.url_in)
        wav = librosa.resample(wav, orig_sr=sr, target_sr=sampling_rate)
        print(wav)

        # Restore model
        G = Generator().to(device)
        print(f'Loading the trained models from step {config.resume_iters}...')
        G_path = join(config.model_save_dir, f'{config.resume_iters}-G.ckpt')
        G.load_state_dict(torch.load(
            G_path, map_location=lambda storage, loc: storage))
        # get reference file
        src_spk_stats = np.load(
            join(config.train_data_dir, f'{config.src_spk}_stats.npz'))
        trg_spk_stats = np.load(
            join(config.train_data_dir, f'{config.trg_spk}_stats.npz'))
        logf0s_mean_src = src_spk_stats['log_f0s_mean']
        logf0s_std_src = src_spk_stats['log_f0s_std']
        logf0s_mean_trg = trg_spk_stats['log_f0s_mean']
        logf0s_std_trg = trg_spk_stats['log_f0s_std']
        feat_mean_src = src_spk_stats['coded_sps_mean']
        feat_std_src = src_spk_stats['coded_sps_std']
        feat_mean_trg = trg_spk_stats['coded_sps_mean']
        feat_std_trg = trg_spk_stats['coded_sps_std']
        spk_idx_trg = spk2idx[config.trg_spk]
        spk_idx_src = spk2idx[config.src_spk]
        spk_cat_trg = to_categorical(
            [spk_idx_trg], num_classes=len(speakers))
        spk_cat_src = to_categorical(
            [spk_idx_src], num_classes=len(speakers))
        spk_c_trg = spk_cat_trg
        spk_c_src = spk_cat_src
        spk_c_mix = spk_cat_trg*1
        # convert
        # 5ms*16kHz = 80samples/frame, nframes = CHUNK/80 = 1000
        f0, timeaxis, sp, ap = world_decompose(
            wav, fs=sampling_rate, frame_period=5)
        #print("f0: ", np.average(f0), "hz")
        #print("sp shape: ", sp.shape)
        coded_sp = world_encode_spectral_envelop(
            sp=sp, fs=sampling_rate, dim=num_mcep)
        coded_ap = world_encode_aperiodic(ap, sampling_rate)
        # decide feature type
        feature = coded_sp
        if config.feat_type == 'apsp':
            feature = np.concatenate(
                (coded_sp, coded_ap, coded_ap, coded_ap, coded_ap), axis=1)
            assert(feature.shape[1] == 60)

        # normalizationi
        feature_norm = (feature - feat_mean_src) / \
            feat_std_src
        feature_norm_tensor = torch.FloatTensor(
            feature_norm.T).unsqueeze_(0).unsqueeze_(1).to(device)
        conds = torch.FloatTensor(spk_c_trg).to(device)
        print("Before being fed into G: ", coded_sp.shape)

        spk_conds = torch.FloatTensor(spk_c_mix).to(device)
        #spk_conds = torch.FloatTensor([0.5, 0.5]).to(device)
        # print(spk_conds.size())
        feature_converted_norm = G(
            feature_norm_tensor, spk_conds).data.cpu().numpy()
        feature_converted = np.squeeze(
            feature_converted_norm).T * feat_std_trg + feat_mean_trg
        feature_converted = np.ascontiguousarray(feature_converted)
        print("After being fed into G: ", feature_converted.shape)
        if config.feat_type == 'apsp' or config.feat_type == 'sp':
            wav_transformed = world_speech_synthesis(f0=f0*0.8, coded_sp=feature_converted, coded_ap=coded_ap,
                                                     fs=sampling_rate, frame_period=frame_period, feat=config.feat_type)
        else:
            assert False, "Not a valid feature type!"
        sf.write(join(config.url_out, 'output.wav'),
                 wav_transformed, sampling_rate)


def web_voice_convert(in_url, out_url):
    parser = argparse.ArgumentParser()

    # Model configuration.
    parser.add_argument('--num_speakers', type=int, default=2,
                        help='dimension of speaker labels')
    parser.add_argument('--resume_iters', type=int,
                        default=250000, help='step to resume for testing.')
    parser.add_argument('--src_spk', type=str, default='falset',
                        help='target speaker.')  # MODIFY
    parser.add_argument('--trg_spk', type=str, default='chest',
                        help='target speaker.')  # MODIFY
    parser.add_argument('--feat_type', type=str,
                        default='apsp', help='target speaker.')
    # Directories.
    parser.add_argument('--train_data_dir', type=str,
                        default='data/codedApSp_belt56_a/train')

    parser.add_argument('--model_save_dir', type=str, default='./models')
    parser.add_argument('--convert_dir', type=str, default='./converted')
    # urls
    parser.add_argument('--use_url', type=bool, default=True)
    parser.add_argument('--url_in', type=str, default=in_url)
    parser.add_argument('--url_out', type=str, default=out_url)

    config = parser.parse_args()
    test(config)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    # Model configuration.
    parser.add_argument('--num_speakers', type=int, default=2,
                        help='dimension of speaker labels')
    parser.add_argument('--num_converted_wavs', type=int,
                        default=6, help='number of wavs to convert.')
    parser.add_argument('--resume_iters', type=int,
                        default=None, help='step to resume for testing.')
    parser.add_argument('--src_spk', type=str, default='chest',
                        help='target speaker.')  # MODIFY
    parser.add_argument('--trg_spk', type=str, default='falset',
                        help='target speaker.')  # MODIFY

    # Directories.
    parser.add_argument('--train_data_dir', type=str,
                        default='data/codedApSp_belt56_a/train')
    parser.add_argument('--test_data_dir', type=str, default='./data/mc/test')
    parser.add_argument('--wav_dir', type=str, default="./data/wav16")
    parser.add_argument('--log_dir', type=str, default='./logs')
    parser.add_argument('--model_save_dir', type=str, default='./models')
    parser.add_argument('--convert_dir', type=str, default='./converted')

    config = parser.parse_args()

    print(config)
    if config.resume_iters is None:
        raise RuntimeError("Please specify the step number for resuming.")
    test(config)
