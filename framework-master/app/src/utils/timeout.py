import inspect
import threading
from functools import wraps
from ollama import ChatResponse


def enforce_timeout(func):
    """Decorator to enforce a strict timeout using daemon threads."""

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        sig = inspect.signature(func)
        bound_args = sig.bind(self, *args, **kwargs)
        bound_args.apply_defaults()

        timeout_seconds = bound_args.arguments.get("timeout_seconds")

        if not timeout_seconds:
            return func(self, *args, **kwargs)

        result_container = []
        exception_container = []

        def target():
            try:
                result_container.append(func(self, *args, **kwargs))
            except Exception as e:
                exception_container.append(e)

        thread = threading.Thread(target=target, daemon=True)
        thread.start()

        thread.join(timeout_seconds)

        if thread.is_alive():
            error_msg = f"Timeout Error: Execution of '{func.__name__}' exceeded {timeout_seconds} seconds."
            print(f"\n[!] {error_msg}")

            from app.src.models.ollama_model import MessageRoleEnum

            return ChatResponse(
                message={"role": MessageRoleEnum.assistant, "content": error_msg},
            )

        if exception_container:
            raise exception_container[0]

        return result_container[0]

    return wrapper
