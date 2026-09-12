class DomainError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def not_found(entity: str, identity: int) -> DomainError:
    return DomainError("NOT_FOUND", f"{entity} {identity} 不存在", 404)
