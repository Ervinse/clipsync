"""应用日志：让 app 下各模块的 logger 输出到标准错误（Docker 部署即容器日志）

uvicorn 只配置自己的 uvicorn.* logger，不配置根 logger；不在这里设置的话，根 logger 默认 WARNING 且没有输出，
logger.info 写的「超管查看用户内容」「超管下载用户文件」「登记新部署」等记录都会被丢掉。
只配置 app 这一支，不动根 logger 与第三方库的日志；propagate 保持开启，测试的 caplog 仍能收到。
"""
import logging

APP_LOGGER_NAME = "app"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def setup_app_logging(level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(APP_LOGGER_NAME)
    logger.setLevel(level)
    # 重复调用（如 --reload 重新导入）时不重复加 handler，避免每条日志打印多次
    if not any(getattr(handler, "_clipsync_app_handler", False) for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        handler._clipsync_app_handler = True
        logger.addHandler(handler)
    return logger
