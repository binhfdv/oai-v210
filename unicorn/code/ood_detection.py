from sklearn.manifold import TSNE
import numpy as np
from sklearn.neighbors import KNeighborsClassifier, KNeighborsRegressor, NearestNeighbors
from sklearn.linear_model import LogisticRegression
from sklearn.cluster import KMeans
from tqdm import tqdm
from data_generator import LoadData
import torch
from test_model import chop_trace_to_subtrace


def distance_function(a,b):
    a = np.squeeze(a)
    b = np.squeeze(b)
    distance = np.linalg.norm(a-b)
    
    return distance

def knn_ood_detector(all_classes, ID_classes, pred_dict_id, test_feature_dict, test_subtrace_dict, feature_dimension, k_neighbour):
                     
	# preparing for KNN fitting

	all_classes_array = np.empty(shape=[0, feature_dimension])
	all_classes_y = np.empty(shape=[0])
	train_set_stride_list = []
    
	for class_index in list(pred_dict_id.keys()):  # for id classes
		this_class_array = np.squeeze(np.array(pred_dict_id[class_index]))
		this_class_y = np.ones((this_class_array.shape[0]))*(class_index)
		train_set_stride_list.append(this_class_array.shape[0])
		all_classes_y = np.concatenate((all_classes_y, this_class_y), axis=0)
		all_classes_array = np.concatenate((all_classes_array, this_class_array), axis=0)
    
	X_train = all_classes_array
	y_train = all_classes_y

	knn = NearestNeighbors(n_neighbors=k_neighbour, metric='euclidean', algorithm='ball_tree')
	knn.fit(X_train, y_train)

	start = 0 
	center_list, max_distance_list = [], []
	for i in range(len(list(pred_dict_id.keys()))):
	# for each in distribution class
		this_X_train = X_train[start:start+train_set_stride_list[i]]
		start += train_set_stride_list[i]
		this_center = np.mean(this_X_train, axis=0)
		center_list.append(this_center)
		distance_list = []
		for X in this_X_train:
			distance_list.append(distance_function(X,this_center))
			
		# now find the max distance as the distance where 95% of samples are calculated as ID
		distance_list.sort()
		distance_list = distance_list[:int(0.95*len(distance_list))]
		max_distance_list.append(np.max(distance_list))
				
	# Now the center of all clusters are ready in center_list
	# and max distance for each cluster is also determined

	# go through the test set and for each sample find the nearest neighbours
	all_classes_array = np.empty(shape=[0, feature_dimension])
	stride_list = []

	ood_detection_rate = []
	print('running ood detection')
	for class_index,traffic in enumerate(all_classes):
		X_test = np.array(test_feature_dict[class_index])
		test_subtrace_list = test_subtrace_dict[class_index]
		#print(traffic)
		ood_counter = 0
		for test_index in range(X_test.shape[0]):
			X = X_test[test_index]
			subtrace = test_subtrace_list[test_index] 
			#print(X.shape)
			# find the k nearest neighbours:
			knn_prediction = knn.kneighbors(X)
			neighbour_distances = list(np.squeeze(knn_prediction[0]))
			neighbour_indexes = list(np.squeeze(knn_prediction[1]))
			# print(neighbour_distances)
			# print(neighbour_indexes)
 
			ood_decision = []
			class_list_for_this_X = []
			for neighbour_index, neighbour_distance in zip(neighbour_indexes, neighbour_distances):
				# if 'ID' in ood_decision: 
				#     break
				# else: # check this test sample only if it is not decided as part of another cluster yet
				
				this_neighbour = X_train[neighbour_index]
				this_neighbour_class = int(y_train[neighbour_index])
				this_neighbour_distance_from_cluster_center = distance_function(this_neighbour , center_list[this_neighbour_class])
				this_X_distance_from_cluster_center = distance_function(X , center_list[this_neighbour_class])
				this_cluster_max_distance = max_distance_list[this_neighbour_class]
				if this_X_distance_from_cluster_center <= this_neighbour_distance_from_cluster_center and this_X_distance_from_cluster_center <= this_cluster_max_distance:
					ood_decision.append('ID')
					class_list_for_this_X.append(this_neighbour_class)
				else:
					ood_decision.append('OOD')
                    
			if 'ID' not in ood_decision:
				ood_counter += 1
    
		# now we have ood_counter for all the samples in the test class, get accuracy
		ood_detection_rate.append(ood_counter/X_test.shape[0])
	return ood_detection_rate

def in_distribution_clusters(ds_file, norm_param_path, model, all_classes, ID_classes, slice_len):
    
	# We don't need gradients on to do reporting
	model.train(False)
	model.cuda()
	# model.cpu()
	model.eval()

	Loader = LoadData(ds_file, key='train', normalize=True, norm_par_path=norm_param_path)
	train_data_dict =  Loader.create_data_dict()
	    
	pred_dict_id = {}
 
	with torch.no_grad():
		for i in tqdm(train_data_dict):
			this_list = train_data_dict[i]
			this_ID_class_index = ID_classes.index(all_classes[i])
			pred_dict_id[this_ID_class_index] = []
			for this_trace in this_list:
				subtrace_list = chop_trace_to_subtrace(this_trace, 200)
				for subtrace in subtrace_list:
				#subtrace = this_trace
                
					start = 0
					prob_sum = 0
					feature_sum = 0
					while start <= subtrace.shape[0]-slice_len:
						this_slice = subtrace[start:start+slice_len,:]
						this_slice = this_slice.unsqueeze(0)
						this_slice = this_slice.unsqueeze(0)
						this_slice = this_slice.float().cuda()
						feature, label_hat = model(this_slice)
						start+=1

						feature = feature.cpu().detach().numpy()
						#pred_dict_id[i].append(feature)
						feature_sum += feature
    
					pred_dict_id[this_ID_class_index].append(feature_sum)
    
	return pred_dict_id

if __name__ == '__main__':
    from tqdm import tqdm


