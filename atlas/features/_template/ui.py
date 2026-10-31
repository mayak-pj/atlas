from atlas.core.feature import Feature


class TemplateFeature(Feature):
    def on_start(self):
        """Подписки: self.ctx.bus.subscribe(...); сервисы: self.ctx.services.register(...)."""

    def create_tab(self):
        return None
