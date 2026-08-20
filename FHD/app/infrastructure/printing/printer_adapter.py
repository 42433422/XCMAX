"""
打印基础设施实现

负责打印服务的具体实现
"""

from abc import ABC, abstractmethod
from typing import Any


class PrinterPort(ABC):
    """打印机端口接口"""

    @abstractmethod
    def print_labels(self, label_data: list[dict[str, Any]]) -> dict[str, Any]:
        """打印标签"""
        pass

    @abstractmethod
    def get_status(self) -> dict[str, Any]:
        """获取打印机状态"""
        pass


class PrinterAdapter(PrinterPort):
    """打印机适配器"""

    def __init__(self):
        pass

    def print_labels(self, label_data: list[dict[str, Any]]) -> dict[str, Any]:
        """打印标签"""
        return {"success": True, "message": "打印任务已提交", "count": len(label_data)}

    def get_status(self) -> dict[str, Any]:
        """获取打印机状态"""
        return {"status": "ready", "message": "打印机就绪"}

    def list_printers(self) -> list[dict[str, Any]]:
        from app.utils.path_io.print_utils import PrinterUtils

        return PrinterUtils().get_available_printers()

    def get_default_printer(self) -> str | None:
        from app.utils.path_io.print_utils import PrinterUtils

        return PrinterUtils().get_default_printer()

    def set_default_printer(self, printer_name: str) -> bool:
        from app.utils.path_io.printer_automation import PrinterAutomation

        return PrinterAutomation().set_default_printer(printer_name)


def get_printer_adapter() -> PrinterPort:
    """获取打印机适配器"""
    return PrinterAdapter()
