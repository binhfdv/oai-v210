from torch.utils.data import Dataset, DataLoader
import numpy as np
import torch
import pickle
from tqdm import tqdm
import random
import torchaudio.functional as audiofunc

class LoadData:
    def __init__(self, dataset_pkls, key, normalize, norm_par_path):
        self.obs_input, self.obs_labels = None, None
        self.norm_params = None
        self.key = key

        if norm_par_path != "":
            self.norm_params = pickle.load(open(norm_par_path, 'rb'))

        dataset = pickle.load(open(dataset_pkls, 'rb'))

        if normalize:
            norm_key = 'norm'
        else:
            norm_key = 'no_norm'

        if (self.obs_input is None) and (self.obs_labels is None):
            self.obs_input, self.obs_labels = dataset[self.key]['samples'][norm_key], dataset[self.key]['labels']


    def create_data_dict(self):
        data_dict = {}
        # after sanitizing, now create the data_dict:
        unique_labels, unique_count = np.unique(np.array(self.obs_labels), return_counts=True)
        print(unique_labels)
        for label in unique_labels:
            data_dict[label] = []
        print('Creating the data_dict')
        for input,label in tqdm(zip(self.obs_input,self.obs_labels)):
            data_dict[int(label)].append(input)

        return data_dict

    def info(self):
        unique_labels, unique_count = np.unique(np.array(self.obs_labels), return_counts=True)
        ds_info = {
            'numfeats': self.obs_input.shape[2],
            'slice_len': self.obs_input.shape[1],
            'numsamps': self.obs_input.shape[0],
            'nclasses': len(unique_labels),
            'samples_per_class': unique_count
        }
        return ds_info



class TrainORANTracesDataset(Dataset):

    def __init__(self, data_dict, indistribution, slice_len):
        self.slice_len = slice_len
        self.data_dict = {}
        print('we are in data generator')
        print(indistribution)
        print(data_dict.keys())
        print('-------------------------------')
        for i,label in enumerate(indistribution): # only the ID classes are added to data_dict
            self.data_dict[i] = data_dict[label]

    def __len__(self):
        length = 0
        for key in self.data_dict:
            length += len(self.data_dict[key])*1000
        return length*2

    def __getitem__(self, idx):
        #Generate two samples of data (anchor and positive)
        this_random_class = random.sample(list(self.data_dict.keys()), 1)[0]
        anchor_and_positive = random.sample(self.data_dict[this_random_class], 2)
        X = anchor_and_positive[0]
        random_index = random.randrange(X.shape[0]-self.slice_len)
        X = X[random_index:random_index+self.slice_len,:]
        X = X.unsqueeze(0)
        
        positive_sample = anchor_and_positive[1]
        # take a random slice from the loaded trace:
        random_index = random.randrange(positive_sample.shape[0]-self.slice_len)
        positive_sample = positive_sample[random_index:random_index+self.slice_len,:]
        positive_sample = positive_sample.unsqueeze(0)
        y = this_random_class

        ## load the negative sample
        negative_class_list = list(self.data_dict.keys())
        negative_class_list.remove(this_random_class)
        negative_class = random.sample(negative_class_list, 1)[0]
        negative_sample = random.sample(self.data_dict[negative_class], 1)[0]
        # take a random slice from the loaded trace:
        random_index = random.randrange(negative_sample.shape[0]-self.slice_len)
        negative_sample = negative_sample[random_index:random_index+self.slice_len,:]
        negative_sample = negative_sample.unsqueeze(0)
        #negative_grid = np.moveaxis(negative_grid, -1, 0)

        return X, positive_sample, negative_sample, y


