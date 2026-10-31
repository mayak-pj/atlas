from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLabel

from atlas.core.feature import Feature
from atlas.features.hello.logic import greeting


class HelloFeature(Feature):
    def on_start(self):
        self.ctx.services.register("hello", self)

    def greet(self, name=None):
        return greeting(name)

    def create_tab(self):
        label = QLabel(greeting())
        label.setAlignment(Qt.AlignCenter)
        return label

    def on_stop(self):
        self.ctx.services.unregister("hello")
