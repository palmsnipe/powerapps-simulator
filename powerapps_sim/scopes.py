"""Lexical scope bookkeeping lives outside authored Power Fx field names."""


class ScopeFrame(dict):
    def __init__(self, fields=(), *, sources=None, aliased=False, open_schema=False):
        super().__init__(fields)
        self.sources = dict(sources or {})
        self.aliased = aliased
        self.open_schema = open_schema

    def typed(self, convert):
        return ScopeFrame({name: convert(name, value) for name, value in self.items()},
                          sources={name: convert(None, value) for name, value in self.sources.items()},
                          aliased=self.aliased, open_schema=self.open_schema)
