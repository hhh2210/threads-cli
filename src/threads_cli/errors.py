class ThreadsError(Exception):
    def __init__(self, code: str, message: str, exit_code: int = 5):
        self.code = code
        self.message = message
        self.exit_code = exit_code
        super().__init__(message)

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message}
