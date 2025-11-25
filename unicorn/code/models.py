import torch
import torch.nn as nn


def model_loader(model_flag, num_classes, weight_path):
	if model_flag == 'ResConvNet':
		model = ResConvNet(num_classes)
	elif model_flag == 'ForwConvNet':
		model = ForwConvNet(num_classes)
	else:
		print('Inappropriate model_flag')

	if weight_path != '':
		model.load_state_dict(torch.load(weight_path,weights_only=True))
	return model

class ResConvNet(nn.Module):
	""" input shape needs to be (b, 1, 64, 17) """
	def __init__(self,num_classes):
		super(ResConvNet, self).__init__()
		dropProb = 0.25
		channel = 32 
		self.conv1 = nn.Conv2d(1, channel, kernel_size=(7,7), padding="same")
		self.conv2 = nn.Conv2d(channel, channel, kernel_size=(5, 5), padding="same")
		self.pool1 = nn.MaxPool2d((2,2))
		self.pool2 = nn.MaxPool2d((3, 3), padding=1)
		self.hidden1 = nn.Linear(128, 128)
		self.hidden2 = nn.Linear(128, 128)  
		self.hidden3 = nn.Linear(128, 64)

		self.out = nn.Linear(64, num_classes)
		self.drop = nn.Dropout(dropProb)
		self.relu = nn.ReLU()
		self.tanh = nn.Tanh()
		self.softmax = nn.Softmax()
		self.sigmoid = nn.Sigmoid()

	def forward(self, x): 
		x = self.relu(self.conv1(x))
		x = self.pool1(x)

		a = x
		x = self.relu(self.conv2(x))
		x = self.relu(self.conv2(x))     
		x = torch.add(x, a)
		x = self.pool2(x)
		x = self.drop(x)

		b = x
		x = self.relu(self.conv2(x))
		x = self.relu(self.conv2(x))     
		x = torch.add(x, b)
		x = self.pool2(x)
		x = self.drop(x)


		x = x.view(x.size(0), -1)
		x = self.hidden1(x)
		x = self.drop(x)

		x = self.hidden2(x)
		x = self.drop(x)
		feature = x
		x = self.hidden3(x)
		x = self.drop(x)

		x = self.out(x) 

		return feature, x




class ForwConvNet(nn.Module):
	""" input shape needs to be (b, 1, 64, 17) """
	def __init__(self,num_classes):
		super(ForwConvNet, self).__init__()
		dropProb = 0.25
		channel = 32 
		self.conv1 = nn.Conv2d(1, channel, kernel_size=(5, 5), padding="same")
		self.conv2 = nn.Conv2d(channel, channel, kernel_size=(3, 3), padding="same")
		self.pool1 = nn.MaxPool2d((2,2))
		self.pool2 = nn.MaxPool2d((3, 3), padding=1)
		self.hidden1 = nn.Linear(512, 256)    
		self.hidden2 = nn.Linear(256, 128)  
		self.hidden3 = nn.Linear(128, 64)

		self.out = nn.Linear(64, num_classes)
		self.drop = nn.Dropout(dropProb)
		self.relu = nn.ReLU()
		self.tanh = nn.Tanh()
		self.softmax = nn.Softmax()
		self.sigmoid = nn.Sigmoid()

	def forward(self, x): 
		x = self.relu(self.conv1(x))
		x = self.pool1(x)

		x = self.relu(self.conv2(x))
		x = self.pool1(x)
		x = self.relu(self.conv2(x))    
		x = self.pool1(x)
		x = self.drop(x)


		x = x.view(x.size(0), -1)
		# print(x.shape)
		x = self.hidden1(x)
		x = self.drop(x)

		x = self.hidden2(x)
		x = self.drop(x)
		feature = x
		x = self.hidden3(x)
		x = self.drop(x)


		x = self.out(x)  # no softmax: CrossEntropyLoss()
		return feature, x

if __name__ == '__main__':
	
	num_classes=5
    
	# weight_path = '../results/ForwConvNet/weights-ICMLCN3-5ids-oodindex3.pt'
	# model = model_loader('ForwConvNet', num_classes, weight_path)

	weight_path = '../weights-ICMLCN4-5ids-oodindex4.pt'
	model = model_loader('ResConvNet', num_classes, weight_path)



	dummy_input = torch.rand((1,1,64,17))

	dummy_feature, dummy_output = model(dummy_input)

	print(dummy_output.shape)

	# print number of parameters in the model
	pp=0
	for p in list(model.parameters()):
		n=1
		for s in list(p.size()):
			n = n*s
		pp += n
	print('This model has ' +str(pp)+ ' parameters')
