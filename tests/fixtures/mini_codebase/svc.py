from util import helper


class Service(Base):
    def run(self):
        return helper()

    def _priv(self):
        return self.run()
