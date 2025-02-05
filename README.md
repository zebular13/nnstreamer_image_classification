# NNstreamer Image Classification
NNStreamer Image Classification example on MaaXBoard OSM93

## Instructions
On the MaaXBoard OSM93, download the model and label files.

Get model:

```wget https://raw.githubusercontent.com/nnsuite/testcases/master/DeepLearningModels/tensorflow-lite/Mobilenet_v1_1.0_224_quant/labels.txt```

Get labels:

```wget https://github.com/nnsuite/testcases/raw/refs/heads/master/DeepLearningModels/tensorflow-lite/Mobilenet_v1_1.0_224_quant/mobilenet_v1_1.0_224_quant.tflite```


## Usage
Run on NPU:

```python3 nnstreamer_image_classification_example.py```

Run on CPU:

```python3 nnstreamer_image_classification_example.py --cpu```
