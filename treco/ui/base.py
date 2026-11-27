class Screen:
    """Contrato de uma aba: desenhar, tratar teclas e (opcionalmente) reagir ao tempo."""
    name = ""
    captures_keys = ()     # teclas que a tela trata ANTES dos atalhos globais

    def __init__(self, app):
        self.app = app

    def draw(self, y0, h, w):
        pass

    def on_key(self, key):
        pass

    def tick(self):
        pass

    def on_escape(self):
        """Retorne True se o ESC foi consumido (senão o ESC fecha o app)."""
        return False

    def on_enter(self):
        """Chamada quando a aba passa a ser a ativa."""

    def cursor_item(self):
        """Faixa sob o cursor (usada pela tecla F → fila). None se não houver."""
        return None

    def footer(self):
        return []
