# import the required packages
import os
import pickle
from tqdm import tqdm
import numpy as np
import glob
import random
import argparse

import torch
import torch.nn as nn
import torch.optim
from torch.utils.data import Dataset, DataLoader

from train_model import train_model
from data_generator import LoadData, TrainORANTracesDataset
from models import model_loader
from ood_detection import in_distribution_clusters, knn_ood_detector 
from test_model import test_model

if __name__ == "__main__":

	parser = argparse.ArgumentParser(description = 'Train and Test pipeline for joint classification and OOD detection for UNICORN',formatter_class=argparse.ArgumentDefaultsHelpFormatter)

	parser.add_argument('--gpu_id', default=0, type=int, help='ID of GPU to be used')
	parser.add_argument('--OOD_class', default='', type=str, help='can be: CallofDuty, Facebook, Meet, Zoom, Teams, Twitch')
	parser.add_argument('--model_flag', default='', type=str, help='can be: ResConvNet or ForwConvNet')
	parser.add_argument('--weight_filename', default='', type=str, help='name of the .pt file containing weights')
	parser.add_argument('--Train', action='store_true', help='Set to true in interested in training')	
	parser.add_argument('--Test', action='store_true', help='Set to true in interested in test')	
    
	args = parser.parse_args()


	all_classes = ['CallofDuty','Facebook','Meet','Zoom','Teams','Twitch']
	OOD_index = all_classes.index(args.OOD_class)

	ds_file = os.path.abspath(os.path.join('../pkls/ICMLCN'+str(OOD_index)+'_dataset_globalnorm.pkl'))
	norm_param_path = os.path.abspath(os.path.join('../pkls/ICMLCN'+str(OOD_index)+'_global_cols_maxmin.pkl'))

	ID_classes = list(filter(lambda x: all_classes[x] != args.OOD_class , range(len(all_classes))))

	print(all_classes)
	print(ID_classes)	
		

	filename_suffix = 'ICMLCN'+str(OOD_index)+'-'+args.model_flag+'-5ids-oodindex'+str(OOD_index)

	args.save_path = os.path.abspath('../results')
	args.weight_path = os.path.join(args.save_path, args.weight_filename)
	args.slice_len = 64 
	args.batch_size = 64 
	args.epochs = 300           # Number of epochs you want to train for
	args.early_stopping = True  # Set to True or False to enable or disable early stopping
	# If early_stopping is enabled, patience shows the number of consecutive epochs
	# after which training stops if training loss does not improve.
	args.patience = 7 

	## create necessary directories
	if not os.path.exists(args.save_path):
		os.makedirs(args.save_path)


	# Initial configurations
	os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
	os.environ["CUDA_VISIBLE_DEVICES"] = str(args.gpu_id)

   
	num_classes = len(ID_classes)
	model = model_loader(args.model_flag, num_classes, '')

	# print number of parameters in the model
	pp=0
	for p in list(model.parameters()):
		n=1
		for s in list(p.size()):
			n = n*s
		pp += n
	print('This model has ' +str(pp)+ ' parameters')


	if args.Train:

		Loader = LoadData(ds_file, key='train', normalize=True, norm_par_path=norm_param_path)
		train_data_dict =  Loader.create_data_dict()
		Loader = LoadData(ds_file, key='val', normalize=True, norm_par_path=norm_param_path)
		val_data_dict =  Loader.create_data_dict()

		print('Training set class population for: ')
		print(train_data_dict.keys())
		for key in train_data_dict:
			print(len(train_data_dict[key]))
		print('------------------------')

		print(train_data_dict.keys())

		train_dataset = TrainORANTracesDataset(train_data_dict, ID_classes, args.slice_len)
		val_dataset = TrainORANTracesDataset(val_data_dict, ID_classes, args.slice_len)

		train_dl = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True, num_workers=2, pin_memory=True)
		val_dl = DataLoader(val_dataset, batch_size=args.batch_size, shuffle=False, num_workers=2, pin_memory=True)

		print(len(train_dl))
		print(len(val_dl))
		# for anchor, positive, negative in train_dl:
		#   print(anchor.shape, positive.shape, negative.shape)
		#     continue
		model = train_model(model, train_dl, val_dl, args, filename_suffix)

	# --------------- Training done --------------- Now Test ---------------------


	args.subtrace_len = 200 
	ID_classes = list(filter(lambda x: x!=args.OOD_class , all_classes))
	num_classes = len(ID_classes)
	
	if not args.Train:    # if training was not done, you have to specify the weight_path
		model = model_loader(args.model_flag, num_classes, args.weight_path)

	if args.Test:

		# --------------- Forming ID clusters predeployment -----------------
		pred_dict_id = in_distribution_clusters(ds_file, norm_param_path, model, all_classes, ID_classes, args.slice_len)


		# -------------- Test on the test set -----------------

		pred_dict, correct_slice_count, total_slice_count, correct_subtrace_count, total_subtrace_count = test_model(model, ds_file, norm_param_path, all_classes, ID_classes, args.slice_len, args.subtrace_len, False)
		print(pred_dict.keys())
		print('how many ID classes')
		print(pred_dict['outlayer'].keys())
		print(len(total_slice_count))

		# subtraces that were fed to the NN are also included in pred_dict

		with open(os.path.join(args.save_path, 'pred_dict-'+args.model_flag+'-oodindex'+str(OOD_index)+'.pkl'), 'wb') as handle:
			pickle.dump(pred_dict,handle,protocol=pickle.HIGHEST_PROTOCOL)

		for label in range(len(total_slice_count)):
			print(correct_slice_count[label]/total_slice_count[label])
		print('total slice accuracy')
		print(np.sum(correct_slice_count)/np.sum(total_slice_count))
		print('----------------------------')
		for label in range(len(total_subtrace_count)):
			print(correct_subtrace_count[label]/total_subtrace_count[label])
		print('total subtrace accuracy:')
		print(np.sum(correct_subtrace_count)/np.sum(total_subtrace_count))


		# KNN OOD detection accuracy
    
		print('OOD results')
		feature_dimension = int(2*args.slice_len)

		test_feature_dict = pred_dict['features']
		test_subtrace_dict = pred_dict['subtraces']
		ood_rate_dict = {}   

		for k_neighbour in [5,10,15]:
			ood_detection_rate = knn_ood_detector(all_classes, ID_classes, pred_dict_id, test_feature_dict, test_subtrace_dict, feature_dimension, k_neighbour)
			print('--------------------------------------')
			print('k = ' +str(k_neighbour))
			for i in ood_detection_rate:
				print(i)
			ood_rate_dict[k_neighbour] = ood_detection_rate

		with open(os.path.join(args.save_path,'ood_rate-'+args.model_flag+'-oodindex'+str(OOD_index)+'.pkl'), 'wb') as handle:
			pickle.dump(ood_rate_dict, handle, protocol=pickle.HIGHEST_PROTOCOL)
