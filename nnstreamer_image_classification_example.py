"""
Based on NNStreamer exmples: https://github.com/nnsuite/nnstreamer

Image classification on MaaXBoard OSM93 using NNStreamer and tensorflow-lite.

Pipeline :
v4l2src -- tee -- textoverlay -- imxvideoconvert -- fpsdisplaysink
            |
            --- imxvideoconvert -- videoconvert -- tensor_converter -- tensor_filter -- tensor_sink

This app displays video sink.

'tensor_filter' for image classification.
Get model: 
wget https://raw.githubusercontent.com/nnsuite/testcases/master/DeepLearningModels/tensorflow-lite/Mobilenet_v1_1.0_224_quant/labels.txt
Get labels:
wget https://github.com/nnsuite/testcases/raw/refs/heads/master/DeepLearningModels/tensorflow-lite/Mobilenet_v1_1.0_224_quant/mobilenet_v1_1.0_224_quant.tflite

'tensor_sink' updates classification result to display in textoverlay.
"""

import os
import sys
import logging
import gi
import argparse

gi.require_version('Gst', '1.0')
from gi.repository import Gst, GObject

# construct the argument parser and parse the arguments
ap = argparse.ArgumentParser()
ap.add_argument('-c', '--cpu', default="False", action='store_true', help="--cpu will run on CPU. Default will run on NPU")
args = ap.parse_args()  

class NNStreamerExample:
    """NNStreamer example for image classification."""

    def __init__(self, argv=None):
        self.loop = None
        self.pipeline = None
        self.running = False
        self.current_label_index = -1
        self.new_label_index = -1
        self.tflite_model = ''
        self.tflite_labels = []

        # Parse command-line arguments
        if args.cpu==True: 
            self.delegate = ''  # No delegate means CPU
            self.accelerator = 'false'
        else:
            self.delegate = 'libethosu_delegate.so' 
            self.accelerator = 'true:npu'

        if not self.tflite_init():
            raise Exception

        GObject.threads_init()
        Gst.init(argv)

    def run_example(self):
        """Init pipeline and run example.

        :return: None
        """
        # main loop
        self.loop = GObject.MainLoop()

        delegate_config = (f'custom=Delegate:External,ExtDelegateLib:{self.delegate} ' 
                           if self.delegate else '')
        # init pipeline
        self.pipeline = Gst.parse_launch(
          'v4l2src name=cam_src ! imxvideoconvert_pxp ! '
          'video/x-raw,width=640,height=480,format=BGRx ! '
          'tee name=t_raw '
          't_raw. ! queue ! textoverlay name=overlay font-desc="Sans, 26" ! '
          'imxvideoconvert_pxp ! fpsdisplaysink name=img_tensor sync=false '
          't_raw. ! queue ! imxvideoconvert_pxp! video/x-raw,width=224,height=224 ! '
          'videoconvert ! video/x-raw,format=RGB ! '
          'tensor_converter ! '
          f'tensor_filter framework=tensorflow-lite model={self.tflite_model} accelerator={self.accelerator} '
          f'{delegate_config}! '
          'tensor_sink name=tensor_sink'
        )

        # bus and message callback
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect('message', self.on_bus_message)

        # tensor sink signal : new data callback
        tensor_sink = self.pipeline.get_by_name('tensor_sink')
        tensor_sink.connect('new-data', self.on_new_data)

        # timer to update result
        GObject.timeout_add(500, self.on_timer_update_result)

        # start pipeline
        self.pipeline.set_state(Gst.State.PLAYING)
        self.running = True

        # set window title
        self.set_window_title('img_test', 'NNStreamer Example')

        # run main loop
        self.loop.run()

        # quit when received eos or error message
        self.running = False
        self.pipeline.set_state(Gst.State.NULL)

        bus.remove_signal_watch()

    def on_bus_message(self, bus, message):
        """Callback for message.

        :param bus: pipeline bus
        :param message: message from pipeline
        :return: None
        """
        if message.type == Gst.MessageType.EOS:
            logging.info('received eos message')
            self.loop.quit()
        elif message.type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            logging.warning('[error] %s : %s', error.message, debug)
            self.loop.quit()
        elif message.type == Gst.MessageType.WARNING:
            error, debug = message.parse_warning()
            logging.warning('[warning] %s : %s', error.message, debug)
        elif message.type == Gst.MessageType.STREAM_START:
            logging.info('received start message')
        elif message.type == Gst.MessageType.QOS:
            data_format, processed, dropped = message.parse_qos_stats()
            format_str = Gst.Format.get_name(data_format)
            logging.debug('[qos] format[%s] processed[%d] dropped[%d]', format_str, processed, dropped)

    def on_new_data(self, sink, buffer):
        """Callback for tensor sink signal.

        :param sink: tensor sink element
        :param buffer: buffer from element
        :return: None
        """
        if self.running:
            for idx in range(buffer.n_memory()):
                mem = buffer.peek_memory(idx)
                result, mapinfo = mem.map(Gst.MapFlags.READ)
                if result:
                    # update label index with max score
                    self.update_top_label_index(mapinfo.data, mapinfo.size)
                    mem.unmap(mapinfo)

    def on_timer_update_result(self):
        """Timer callback for textoverlay.

        :return: True to ensure the timer continues
        """
        if self.running:
            if self.current_label_index != self.new_label_index:
                # update textoverlay
                self.current_label_index = self.new_label_index
                label = self.tflite_get_label(self.current_label_index)
                textoverlay = self.pipeline.get_by_name('overlay')
                textoverlay.set_property('text', label)
        return True

    def set_window_title(self, name, title):
        """Set window title.

        :param name: GstXImageSink element name
        :param title: window title
        :return: None
        """
        element = self.pipeline.get_by_name(name)
        if element is not None:
            pad = element.get_static_pad('sink')
            if pad is not None:
                tags = Gst.TagList.new_empty()
                tags.add_value(Gst.TagMergeMode.APPEND, 'title', title)
                pad.send_event(Gst.Event.new_tag(tags))

    def tflite_init(self):
        """Check tflite model and load labels.

        :return: True if successfully initialized
        """
        if args.cpu==True: 
            tflite_model = 'mobilenet_v1_1.0_224_quant.tflite'
        else:
            tflite_model = 'mobilenet_v1_1.0_224_quant_vela.tflite'
        tflite_label = 'labels.txt'
        current_folder = os.path.dirname(os.path.abspath(__file__))
        model_folder = os.path.join(current_folder, 'tflite_model')

        # check model file exists
        self.tflite_model = os.path.join(model_folder, tflite_model)
        if not os.path.exists(self.tflite_model):
            logging.error('cannot find tflite model [%s]', self.tflite_model)
            return False

        # load labels
        label_path = os.path.join(model_folder, tflite_label)
        try:
            with open(label_path, 'r') as label_file:
                for line in label_file.readlines():
                    self.tflite_labels.append(line)
        except FileNotFoundError:
            logging.error('cannot find tflite label [%s]', label_path)
            return False

        logging.info('finished to load labels, total [%d]', len(self.tflite_labels))
        return True

    def tflite_get_label(self, index):
        """Get label string with given index.

        :param index: index for label
        :return: label string
        """
        try:
            label = self.tflite_labels[index]
        except IndexError:
            label = ''
        return label

    def update_top_label_index(self, data, data_size):
        """Update tflite label index with max score.

        :param data: array of scores
        :param data_size: data size
        :return: None
        """
        # -1 if failed to get max score index
        self.new_label_index = -1

        if data_size == len(self.tflite_labels):
            scores = [data[i] for i in range(data_size)]
            max_score = max(scores)
            if max_score > 0:
                self.new_label_index = scores.index(max_score)
        else:
            logging.error('unexpected data size [%d]', data_size)


if __name__ == '__main__':
    example = NNStreamerExample(sys.argv[1:])
    example.run_example()
