# Software License Agreement (BSD License)
#
# Copyright (c) 2011, Willow Garage, Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
#  * Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#  * Redistributions in binary form must reproduce the above
#    copyright notice, this list of conditions and the following
#    disclaimer in the documentation and/or other materials provided
#    with the distribution.
#  * Neither the name of Willow Garage, Inc. nor the names of its
#    contributors may be used to endorse or promote products derived
#    from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

import os

from ament_index_python import get_resource

from tf2_msgs.srv import FrameGraph
import tf2_ros

from python_qt_binding import loadUi
from python_qt_binding.QtCore import QFile, QIODevice, QObject, Qt, Signal
from python_qt_binding.QtGui import QIcon, QImage, QPainter
from python_qt_binding.QtWidgets import QFileDialog, QGraphicsScene, QWidget
from python_qt_binding.QtSvg import QSvgGenerator
from qt_dotgraph.pydotfactory import PydotFactory
# from qt_dotgraph.pygraphvizfactory import PygraphvizFactory
from qt_dotgraph.dot_to_qt import DotToQtGenerator
from rqt_graph.interactive_graphics_view import InteractiveGraphicsView

from .dotcode_tf import RosTfTreeDotcodeGenerator


class RosTfTree(QObject):

    _deferred_fit_in_view = Signal()

    def __init__(self, context):
        super(RosTfTree, self).__init__(context)
        self.initialized = False

        self.setObjectName('RosTfTree')

        self._node = context.node

        self._current_dotcode = None

        self._widget = QWidget()

        # factory builds generic dotcode items
        self.dotcode_factory = PydotFactory()
        # self.dotcode_factory = PygraphvizFactory()
        # generator builds rosgraph
        self.dotcode_generator = RosTfTreeDotcodeGenerator()
        self.tf2_buffer_ = tf2_ros.Buffer(node=self._node)
        self.tf2_listener_ = tf2_ros.TransformListener(self.tf2_buffer_, self._node)

        # dot_to_qt transforms into Qt elements using dot layout
        self.dot_to_qt = DotToQtGenerator()

        _, package_path = get_resource('packages', 'rqt_tf_tree')
        ui_file = os.path.join(package_path, 'share', 'rqt_tf_tree', 'resource', 'RosTfTree.ui')
        loadUi(ui_file, self._widget, {'InteractiveGraphicsView': InteractiveGraphicsView})
        self._widget.setObjectName('RosTfTreeUi')
        if context.serial_number() > 1:
            self._widget.setWindowTitle(self._widget.windowTitle() + (' (%d)' % context.serial_number()))

        self._scene = QGraphicsScene()
        self._scene.setBackgroundBrush(Qt.white)
        self._widget.graphics_view.setScene(self._scene)

        self._widget.clear_buffer_push_button.setIcon(QIcon.fromTheme('edit-delete'))
        self._widget.clear_buffer_push_button.pressed.connect(self._clear_buffer)

        self._widget.refresh_graph_push_button.setIcon(QIcon.fromTheme('view-refresh'))
        self._widget.refresh_graph_push_button.pressed.connect(self._update_tf_graph)

        self._widget.highlight_connections_check_box.toggled.connect(self._redraw_graph_view)
        self._widget.auto_fit_graph_check_box.toggled.connect(self._redraw_graph_view)
        self._widget.fit_in_view_push_button.setIcon(QIcon.fromTheme('zoom-original'))
        self._widget.fit_in_view_push_button.pressed.connect(self._fit_in_view)

        self._widget.load_dot_push_button.setIcon(QIcon.fromTheme('document-open'))
        self._widget.load_dot_push_button.pressed.connect(self._load_dot)
        self._widget.save_dot_push_button.setIcon(QIcon.fromTheme('document-save-as'))
        self._widget.save_dot_push_button.pressed.connect(self._save_dot)
        self._widget.save_as_svg_push_button.setIcon(QIcon.fromTheme('document-save-as'))
        self._widget.save_as_svg_push_button.pressed.connect(self._save_svg)
        self._widget.save_as_image_push_button.setIcon(QIcon.fromTheme('image-x-generic'))
        self._widget.save_as_image_push_button.pressed.connect(self._save_image)

        self._deferred_fit_in_view.connect(self._fit_in_view,
                                           Qt.QueuedConnection)
        self._deferred_fit_in_view.emit()

        context.add_widget(self._widget)

        self._force_refresh = False

    def save_settings(self, plugin_settings, instance_settings):
        instance_settings.set_value('auto_fit_graph_check_box_state',
                                    self._widget.auto_fit_graph_check_box.isChecked())
        instance_settings.set_value('highlight_connections_check_box_state',
                                    self._widget.highlight_connections_check_box.isChecked())

    def restore_settings(self, plugin_settings, instance_settings):
        self._widget.auto_fit_graph_check_box.setChecked(
            instance_settings.value('auto_fit_graph_check_box_state', True) in [True, 'true'])
        self._widget.highlight_connections_check_box.setChecked(
            instance_settings.value('highlight_connections_check_box_state', True) in [True, 'true'])
        self.initialized = True
        self._refresh_tf_graph()

    def _clear_buffer(self):
        self.tf2_buffer_.clear()

    def _update_tf_graph(self):
        self._force_refresh = True
        self._refresh_tf_graph()

    def _refresh_tf_graph(self):
        if not self.initialized:
            return
        self._update_graph_view(self._generate_dotcode())

    def _generate_dotcode(self):
        force_refresh = self._force_refresh
        self._force_refresh = False

        tf2_frame_client = self._node.create_client(FrameGraph, 'tf2_frames')
        while not tf2_frame_client.wait_for_service(timeout_sec=1.0):
            print('service not available, waiting again...')

        return self.dotcode_generator.generate_dotcode(dotcode_factory=self.dotcode_factory,
                                                       tf2_frame_srv=tf2_frame_client,
                                                       timer=self._node.get_clock(),
                                                       force_refresh=force_refresh)

    def _update_graph_view(self, dotcode):
        if dotcode == self._current_dotcode:
            return
        self._current_dotcode = dotcode
        self._redraw_graph_view()

    def _generate_tool_tip(self, url):
        return url

    def _redraw_graph_view(self):
        self._scene.clear()

        if self._widget.highlight_connections_check_box.isChecked():
            highlight_level = 3
        else:
            highlight_level = 1

        (nodes, edges) = self.dot_to_qt.dotcode_to_qt_items(self._current_dotcode,
                                                            highlight_level)

        for node_item in nodes.values():
            self._scene.addItem(node_item)
        for edge_items in edges.values():
            for edge_item in edge_items:
                edge_item.add_to_scene(self._scene)

        self._scene.setSceneRect(self._scene.itemsBoundingRect())
        if self._widget.auto_fit_graph_check_box.isChecked():
            self._fit_in_view()

    def _load_dot(self, file_name=None):
        if file_name is None:
            file_name, _ = QFileDialog.getOpenFileName(
                self._widget,
                self.tr('Open graph from file'),
                None,
                self.tr('DOT graph (*.dot)'))
            if file_name is None or file_name == '':
                return

        try:
            fhandle = open(file_name, 'rb')
            dotcode = fhandle.read()
            fhandle.close()
        except IOError:
            return

        self._update_graph_view(dotcode)

    def _fit_in_view(self):
        self._widget.graphics_view.fitInView(self._scene.itemsBoundingRect(),
                                             Qt.KeepAspectRatio)

    def _save_dot(self):
        file_name, _ = QFileDialog.getSaveFileName(self._widget,
                                                   self.tr('Save as DOT'),
                                                   'frames.dot',
                                                   self.tr('DOT graph (*.dot)'))
        if file_name is None or file_name == '':
            return

        file = QFile(file_name)
        if not file.open(QIODevice.WriteOnly | QIODevice.Text):
            return

        file.write(self._current_dotcode)
        file.close()

    def _save_svg(self):
        file_name, _ = QFileDialog.getSaveFileName(
            self._widget,
            self.tr('Save as SVG'),
            'frames.svg',
            self.tr('Scalable Vector Graphic (*.svg)'))
        if file_name is None or file_name == '':
            return

        generator = QSvgGenerator()
        generator.setFileName(file_name)
        generator.setSize((self._scene.sceneRect().size() * 2.0).toSize())

        painter = QPainter(generator)
        painter.setRenderHint(QPainter.Antialiasing)
        self._scene.render(painter)
        painter.end()

    def _save_image(self):
        file_name, _ = QFileDialog.getSaveFileName(
            self._widget,
            self.tr('Save as image'),
            'frames.png',
            self.tr('Image (*.bmp *.jpg *.png *.tiff)'))
        if file_name is None or file_name == '':
            return

        img = QImage((self._scene.sceneRect().size() * 2.0).toSize(),
                     QImage.Format_ARGB32_Premultiplied)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing)
        self._scene.render(painter)
        painter.end()
        img.save(file_name)
