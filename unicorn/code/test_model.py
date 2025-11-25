import torch
import numpy as np
from data_generator import LoadData
from tqdm import tqdm


def chop_trace_to_subtrace(trace, sub_trace_len):
    sub_trace_list = []
    start_index = 0 
    while start_index <= trace.shape[0]-sub_trace_len:
        sub_trace_list.append(trace[start_index:start_index+sub_trace_len,:])
        start_index += sub_trace_len
    return sub_trace_list


def test_model(model, ds_file, norm_param_path, all_classes, ID_classes, slice_len, subtrace_len, rehearsal_buffer):
    model.train(False)
    model.cuda()
    # model.cpu()
    model.eval()
 
    if rehearsal_buffer:
        print('Doing test on training set for rehearsal buffer')
        Loader = LoadData(ds_file, key='train', normalize=True, norm_par_path=norm_param_path)
        test_data_dict =  Loader.create_data_dict()
        all_classes = ID_classes
    else:
        Loader = LoadData(ds_file, key='test', normalize=True, norm_par_path=norm_param_path)
        test_data_dict =  Loader.create_data_dict()
    
    
    print('we are in test_model')
    print('test_data_dict.keys()')
    print(test_data_dict.keys())
    print(ID_classes)
    print(all_classes)

    """print(ID_classes)
    class_list = list(map(lambda x: all_classes.index(x), all_classes))
    print(class_list)
    all_classes = class_list"""
    
   

    """Loader = LoadData(ds_file, key='val', normalize=True, norm_par_path=norm_param_path)
    val_data_dict =  Loader.create_data_dict()"""
    
    
    """for key in [0,1,2,3,4,5]:
        test_data_dict[key] = train_data_dict[key]"""
    
    """for key in [0,1,2,3]:
        test_data_dict[key] += val_data_dict[key]"""
    

    # we send the subtraces out in the same order as the features and outputs
    # this is done for the adaptive framework to have the inputs of ood features for the next round
    subtrace_dict = {}
 

    pred_dict = {}
    out_layer = {}
    feature_dict = {}
    for i,label in enumerate(all_classes):    
        feature_dict[i] = []
        subtrace_dict[i] = []
    for i,label in enumerate(ID_classes):    
        out_layer[i] = []  
    
    total_slice_count = np.zeros((len(ID_classes)))
    correct_slice_count = np.zeros((len(ID_classes)))
    total_subtrace_count = np.zeros((len(ID_classes)))
    correct_subtrace_count = np.zeros((len(ID_classes)))
   
    with torch.no_grad():
    
        for i, label in tqdm(enumerate(all_classes)):   # we test on all_classes 
            this_list = test_data_dict[i]
            for this_trace in this_list:
                subtrace_list = chop_trace_to_subtrace(this_trace, subtrace_len)
                for subtrace in subtrace_list:
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
        
                        if label in ID_classes:  # if this is actually an ID class
                            this_ID_class_index = ID_classes.index(label)
                            label_hat = label_hat.cpu().detach().numpy()
                            if np.argmax(label_hat) == this_ID_class_index:
                                correct_slice_count[this_ID_class_index] += 1
                            total_slice_count[this_ID_class_index] += 1
                            #out_layer[i].append(label_hat)
                            prob_sum += label_hat
                    
                    
                        feature = feature.cpu().detach().numpy()
                        #feature_dict[i].append(feature)
                        feature_sum += feature
    
                    if label in ID_classes:
                        this_ID_class_index = ID_classes.index(label)
                        if np.argmax(prob_sum) == this_ID_class_index:
                            correct_subtrace_count[this_ID_class_index] += 1
                        total_subtrace_count[this_ID_class_index] += 1
                        out_layer[this_ID_class_index].append(prob_sum)
                    
                    # send the subtraces out in the same order as features, regardless of ID or OOD
                    subtrace_dict[i].append(subtrace)
                    feature_dict[i].append(feature_sum)
    
    pred_dict = {'features':feature_dict, 'outlayer':out_layer, 'subtraces':subtrace_dict}

    return pred_dict, correct_slice_count, total_slice_count, correct_subtrace_count, total_subtrace_count



