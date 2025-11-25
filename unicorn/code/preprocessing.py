import numpy as np
import torch
import torch.nn.functional as F
import pandas as pd
import os
from torch.utils.data import Dataset
from torchvision.transforms import ToTensor
from tqdm import tqdm
import pickle
import argparse
from glob import glob
from scipy.stats import norm as normal
import sys



check_zeros = False
drop_colnames = ['Timestamp','num_ues','IMSI','RNTI','slicing_enabled','slice_id','slice_prb','scheduling_policy']

# exclude_cols = [0, 1, 2, 3, 4, 5, 6, 8, 14, 22, 27, 28, 29]

Exp_name = 'ICMLCN5'   
ds_path = '../pkls/'
ds_path = os.path.abspath(ds_path)


# All ID and OOD classes
classmap = {'CallofDuty':0,'Twitch':5,'Teams':4,'Facebook':1, 'Zoom':3, 'Meet':2}

print('got here')
ood_class_index = int(Exp_name.strip('ICMLCN'))
print(ood_class_index)

with open ('../file2app_map.pkl','rb') as handle:
	class_dict = pickle.load(handle)

trace_base_path = '../traces/'
trace_base_path = os.path.abspath(trace_base_path)

## create necessary directories
if not os.path.exists(ds_path):
	os.makedirs(ds_path)


# ------------------------------------------- Functions -------------------------------------------

def check_slices(data, index, check_zeros=False):
	labels = int(index)
	#labels = np.ones((data.shape[0],), dtype=np.int32)*index
	if not check_zeros:
		return labels
	for i in range(data.shape[0]):
		sl = data[i]
		zeros = (sl == 0).astype(int).sum(axis=1)
		if (zeros > 10).all():
			labels[i] = int(len(list(classmap.keys())))  # control if all KPIs rows have > 10 zeros
	return labels


def gen_trace_dataset(trace_base_path, check_zeros, drop_colnames, ood_class_index=9):

	train_trials, val_trials, test_trials = [], [], []
	train_labels, val_labels, test_labels = [], [], []
	  
	cols_names = None
	excluded_indexes_sUE = None
	all_cols_names_sUE = None
	excluded_indexes_mUE = None
	all_cols_names_mUE = None

	trial_samples, cols_n, excluded_indexes_sUE, all_cols_names_sUE = get_trace_singleUE(trace_base_path, drop_colnames, check_zeros, ood_class_index)
	
	if cols_names is None:  # NOTE: assume Trials have all the same columns, we set only once
		cols_names = cols_n
 
	train_trials += trial_samples['train']['traces']
	val_trials += trial_samples['val']['traces']
	test_trials += trial_samples['test']['traces']

	train_labels += trial_samples['train']['labels']
	val_labels += trial_samples['val']['labels']
	test_labels += trial_samples['test']['labels']

	if (not (excluded_indexes_sUE is None ) and not (excluded_indexes_mUE is None)) and (not(all_cols_names_sUE is None) and not (all_cols_names_mUE is None)):
		assert np.all(excluded_indexes_sUE == excluded_indexes_mUE) and np.all(all_cols_names_sUE == all_cols_names_mUE), "Check these are matching for all datasets processed"

	excluded_indexes = excluded_indexes_sUE # since are the same after previous check
	all_cols_names = all_cols_names_sUE
	if (excluded_indexes is None) and (all_cols_names is None):
		excluded_indexes = excluded_indexes_mUE # to address multi UE only dataset case
		all_cols_names = all_cols_names_mUE

	# before normalizing record the trace lengths
	train_trace_lens = []
	for trace in train_trials:
		#print(trace)  # it still has the strings in it
		train_trace_lens.append(trace.shape[0])
	val_trace_lens = []
	for trace in val_trials:
		val_trace_lens.append(trace.shape[0])
	test_trace_lens = []
	for trace in test_trials:
		test_trace_lens.append(trace.shape[0])


	print(len(train_trials))
	print(len(val_trials))
	print(len(test_trials))

	if len(train_trials) != 0:
		train_trials = np.concatenate(train_trials, axis=0).astype(np.float32)
	if len(val_trials) != 0:
		val_trials = np.concatenate(val_trials, axis=0).astype(np.float32)
	if len(test_trials) != 0:
		test_trials = np.concatenate(test_trials, axis=0).astype(np.float32)

	
	columns_maxmin_train = extract_feats_stats(cols_names, train_trials)
	columns_maxmin_val = extract_feats_stats(cols_names, val_trials)
	columns_maxmin_test = extract_feats_stats(cols_names, test_trials)

	train_norm = normalize_KPIs(columns_maxmin_train, train_trials)
	val_norm = normalize_KPIs(columns_maxmin_train, val_trials)
	test_norm = normalize_KPIs(columns_maxmin_train, test_trials)

	# now separate the normalized matrices into lists:
	train_norm_list = []
	start = 0
	for length in train_trace_lens:
		this_trace = train_norm[start:start+length,:]
		train_norm_list.append(torch.tensor(this_trace))
		start += length
	val_norm_list = []
	start = 0
	for length in val_trace_lens:
		this_trace = val_norm[start:start+length,:]
		val_norm_list.append(torch.tensor(this_trace))
		start += length
	test_norm_list = []
	start = 0
	for length in test_trace_lens:
		this_trace = test_norm[start:start+length,:]
		test_norm_list.append(torch.tensor(this_trace))
		start += length
	
	columns_maxmin_train['info'] = {'raw_cols_names': all_cols_names, 'exclude_cols_ix': excluded_indexes} 
 
	nclasses = int(len(list(classmap.keys())))

	print('before sending out')
	print(len(train_labels), len(val_labels), len(test_labels))

	trials_ds = {
		'train': {
			'samples': {
				'no_norm': train_norm_list,
				'norm': train_norm_list
			},
			'labels': train_labels
		},
		'val': {
			'samples': {
				'no_norm': val_norm_list,
				'norm': val_norm_list
			},
			'labels': val_labels
		},
		'test': {
			'samples': {
				'no_norm': test_norm_list,
				'norm': test_norm_list
			},
			'labels': test_labels
		}
	}

	return trials_ds, columns_maxmin_train

def chop_trace_to_subtrace(trace, sub_trace_len):
	sub_trace_list = []
	start_index = 0
	while start_index < trace.shape[0]-sub_trace_len:
		sub_trace_list.append(trace[start_index:start_index+sub_trace_len,:])
		start_index += sub_trace_len
	return sub_trace_list
	

def get_trace_singleUE(trace_base_path, drop_colnames, check_zeros, ood_class_index):
	trace_list, filename_list =  load_csv_dataset__single(trace_base_path)

	train_trace_list, val_trace_list, test_trace_list = [], [], []
	train_label_list, val_label_list, test_label_list = [], [], []

	all_cols_names = None
	cols_names = None
	excluded_indexes = None

	for ix, (trace,filename) in enumerate(zip(trace_list,filename_list)):
		columns_drop = drop_colnames

		# print(filename)
		
		if excluded_indexes is None:	# done only once for all datasets
			excluded_indexes = [trace.columns.get_loc(c) for c in columns_drop]
		if all_cols_names is None:  # only once
			all_cols_names = trace.columns.values   # before drop

		trace.drop(columns_drop, axis=1, inplace=True)

		# NOTE: assuming all the files have same headers and same columns are dropped
		if cols_names is None:   # done only once for all datasets
			cols_names = trace.columns.values   # after drop

		# # remove trace headers
		trace = trace.to_numpy()
		trace = trace[1:,:]

		if trace.shape[0] == 10:
			print(filename)
		
		# Nasim: find the class index:
		class_index = classmap[class_dict[filename]]
		# print('OOD class index')
		# print(ood_class_index)

		subtrace = trace
		if class_index != ood_class_index and (int(filename.split('_')[-1]) < 6000 or int(filename.split('_')[-1]) % 4 == 3 or int(filename.split('_')[-1]) % 4 == 0 or int(filename.split('_')[-1]) % 4 == 1):
			# choose a random index to start the validation set from
			train_trace_list.append(subtrace)
			train_label_list.append(check_slices(subtrace, class_index, check_zeros))
		elif class_index != ood_class_index and (int(filename.split('_')[-1]) < 7000 and int(filename.split('_')[-1]) % 4 == 2):
			val_trace_list.append(subtrace)
			val_label_list.append(check_slices(subtrace, class_index, check_zeros))
		#elif (class_index != ood_class_index) or (class_index == ood_class_index and (int(filename.split('_')[-1]) < 6000 or int(filename.split('_')[-1]) % 4 == 3 or int(filename.split('_')[-1]) % 4 == 0 or int(filename.split('_')[-1]) % 4 == 1)): 
		# elif (class_index != ood_class_index and int(filename.split('_')[-1]) > 7000 and int(filename.split('_')[-1]) % 4 == 2) or \
		#	  (class_index == ood_class_index):  # having large OOD test set
		elif (int(filename.split('_')[-1]) > 7000 and int(filename.split('_')[-1]) % 4 == 2):  # having smaller OOD test set 
			#if int(int(filename.split('_')[-1])/100) % 10 == 3: # indoor: 1, outdoor: 2, outdoor walking: 3
			test_trace_list.append(subtrace)
			test_label_list.append(check_slices(subtrace, class_index, check_zeros))

		
				

	# print('len of train and label')
	# print(len(train_slices))
	# print(len(train_labels))


	return {
		'train': {'traces': train_trace_list, 'labels': train_label_list},
		'val': {'traces': val_trace_list, 'labels': val_label_list},
		'test': {'traces': test_trace_list, 'labels': test_label_list}	   
	}, cols_names, excluded_indexes, all_cols_names


def extract_feats_stats(cols_names, trials_in):
	columns_maxmin = {}
	for c in range(trials_in.shape[-1]):
		col_max = trials_in[:, c].max()
		col_min = trials_in[:, c].min()
		col_mean = trials_in[:, c].mean()
		col_std = trials_in[:, c].std()
		columns_maxmin[c] = {'max': col_max, 'min': col_min, 'mean': col_mean, 'std': col_std, 'name': cols_names[c]}
	return columns_maxmin

def normalize_KPIs(columns_maxmin, trials_in, doPrint=False):
	trials_in_norm = trials_in.copy()
	for c, max_min_info in columns_maxmin.items():
		if isinstance(c, int):
			if max_min_info['name'] != 'Timestamp':
				col_max = max_min_info['max']
				col_min = max_min_info['min']
				if not (col_max == col_min):
					if doPrint:
						print('Normalizing Col.', max_min_info['name'], ' -- Max', col_max, ', Min', col_min)
					trials_in_norm[:, c] = (trials_in_norm[:, c] - col_min) / (col_max - col_min)
				else:
					trials_in_norm[:, c] = 0  # set all data as zero (we don't need this info cause it never changes)
			else:
				if doPrint:
					print('Skipping normalization of Col. ', max_min_info['name'])

	return trials_in_norm


def normalize_RAW_KPIs(columns_maxmin, trials_in, map_feat2KPI, indexes_to_keep, doPrint=False):
	trials_in_norm = trials_in[:,indexes_to_keep].copy()
	for f, max_min_info in columns_maxmin.items():
		if isinstance(f, int):
			c = map_feat2KPI[f]
			col_max = max_min_info['max']
			col_min = max_min_info['min']
			if not (col_max == col_min):
				if doPrint:
					print('Normalizing Col.', max_min_info['name'], '[', c, '] -- Max', col_max, ', Min', col_min)
				trials_in_norm[:, f] = (trials_in_norm[:, f] - col_min) / (col_max - col_min)
			else:
				trials_in_norm[:, f] = 0  # set all data as zero (we don't need this info cause it never changes)
	return trials_in_norm


def load_csv_dataset__single(trace_base_path):
	# for each traffic type, let's load csv info using pandas

	all_file_paths = glob(os.path.join(trace_base_path,'urllc_*.csv'))
	
	all_traces = [pd.read_csv(f, sep=",").dropna(how='all', axis='columns') for f in all_file_paths]  # also remove completely blank columns, if present
	filenames = list(map(lambda x: x.split('/')[-1].split('.csv')[0], all_file_paths))
	
	return all_traces, filenames

def safe_pickle_dump(filepath, myobj):
	yes_choice = ['yes', 'y']
	to_save = True
	if os.path.isfile(filepath):
		user_input = input("File " + filepath + " exists already. Overwrite? [y/n]")
		if not (user_input.lower() in yes_choice):
			to_save = False
	if to_save:
		pickle.dump(myobj, open(filepath, 'wb'))

def relative_timestamp(x):
	first_ts = x[0,0] # get first value of first column (Timestamp)
	x[:, 0] -=  first_ts
	return x

def add_first_dim(x):
	return x[None]




# ------------------------------------------- main () -------------------------------------------



dataset, cols_maxmin = gen_trace_dataset(trace_base_path=trace_base_path, check_zeros=check_zeros, drop_colnames=drop_colnames, ood_class_index=ood_class_index)


# print(dataset['train']['samples']['norm'][0])

dataset_path = os.path.join(ds_path, Exp_name +'_dataset.pkl')
safe_pickle_dump(dataset_path, dataset)
# save separately maxmin normalization parameters for each column/feature
norm_param_path = os.path.join(ds_path, Exp_name +'_cols_maxmin.pkl')
safe_pickle_dump(norm_param_path, cols_maxmin)

datasets = [ (dataset, cols_maxmin, ds_path, norm_param_path) ]



# if multiple data types (i.e. singleUE, multiUE) have been processed,
# let's define a common set of normalization/sanitization parameters

# first, let's find a common set of columns to keep (i.e. the ones that have varying values)
# and their common min max parameters for normalization
common_normp = {}
novar_keys_raw = []
novar_keys = []
common_keys = set()
[common_keys.update(
		set([k for k in kpi_p.keys() if isinstance(k, int)])
	)
	for _, kpi_p, _, _ in datasets]

# verify that the raw column names are all the same  for all datasets
raw_col_names = datasets[0][1]['info']['raw_cols_names']
assert all([np.all(kpi_p['info']['raw_cols_names'] == raw_col_names) for _, kpi_p, _, _ in datasets]), 'Ensure that raw kpis names are the same for all datasets'
exclude_cols_ix = datasets[0][1]['info']['exclude_cols_ix']
assert all([np.all(kpi_p['info']['exclude_cols_ix'] == exclude_cols_ix) for _, kpi_p, _, _ in datasets]), 'Ensure that excluded kpi indexes are the same for all datasets'

for k in common_keys:   # for each common key/kpi featurepickle_ds_path
	# verify that the key names are the same for all datasets
	first_ds_kpiname = datasets[0][1][k]['name']
	assert all([kpi_p[k]['name'] == first_ds_kpiname for _, kpi_p, _, _ in datasets]), 'Ensure that kpis and names have the same order for all datasets'

	# obtain the overall max/min values
	common_normp[k] = {
		'name': first_ds_kpiname,
		'max': max([kpi_p[k]['max'] for _, kpi_p, _, _ in datasets]),	 # get max of maxes in that specific key/feature
		'min': min([kpi_p[k]['min'] for _, kpi_p, _, _ in datasets])	  # get min of mins in that specific key/feature
	}
	# annotate the features indexes that needs to be dropped when re-normalizing and sanitizing the data
	if common_normp[k]['max'] == common_normp[k]['min']:
		for ix, name in enumerate(raw_col_names):	# use the names of first kpi params in the dataset (since they should be all the same)
			if common_normp[k]['name'] == name:
				c = ix
				break
		novar_keys_raw.append(c)
		novar_keys.append(k)

# let's also exclude the indexes from normalization parameters to reflect filtered features
common_normp_filtd = {}
feat_count = 0
for k in common_keys:
	if not(k in novar_keys):
		common_normp_filtd[feat_count] = common_normp[k].copy()
		feat_count += 1
common_normp_filtd['info'] = {'exclude_cols_ix': list(set(novar_keys_raw).union(set(exclude_cols_ix)))}

common_normp = common_normp_filtd   # substitute the common norm parameters with newly filtered ones

global_norm_path = os.path.join(ds_path, Exp_name +'_global_cols_maxmin.pkl')

# until now, we have retained the columns that are not excluded, but we still haven't removed
# the ones without variation (i.e. std = 0).
# we should remove those columns here as well before continuing computation of ctrl template
filtKPI_keep = list(set(range(len(common_keys))).difference(novar_keys))

for ds, kpi_p, ds_path, kpi_p_path in datasets:
	for t in ['train', 'val','test']:
		this_dataset_list_norm = []
		this_dataset_list_no_norm = []
		for trace in ds[t]['samples']['norm']:
			this_dataset_list_norm.append(trace[:, filtKPI_keep])
		for trace in ds[t]['samples']['no_norm']:
			this_dataset_list_no_norm.append(trace[:, filtKPI_keep])
			# print(trace.shape)
			# print(trace[:, filtKPI_keep].shape)
			# print('--------------------')
		ds[t]['samples']['norm'] =  this_dataset_list_norm
		ds[t]['samples']['no_norm'] = this_dataset_list_no_norm
	safe_pickle_dump(os.path.join(ds_path, Exp_name + '_dataset_globalnorm.pkl'), ds)

# lastly, let's save the new global parameters
safe_pickle_dump(global_norm_path, common_normp)
