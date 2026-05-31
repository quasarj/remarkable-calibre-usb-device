import logging

LOGGER = logging.getLogger("remarkable-calibre-usb-device")


def log_args_kwargs(func):
    def wrapper(*args, **kwargs):
        LOGGER.debug(f"__ calibre_remarkable_usb_device call: {func.__name__}, Arguments: {args}, Keyword Arguments: {kwargs}")
        return func(*args, **kwargs)

    return wrapper
