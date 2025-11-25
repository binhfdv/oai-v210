#bin/bash/!
python top.py \
--gpu_id $1 \
--Test \
--OOD_class 'Teams' \
--model_flag 'ResConvNet' \
--weight_filename 'weights-ICMLCN4-ResConvNet-5ids-oodindex4.pt' 
