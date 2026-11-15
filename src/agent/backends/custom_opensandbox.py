"""OpenSandboxBackend 的自定义封装。"""

from datetime import timedelta
from pathlib import PurePosixPath

from deepagents.backends.protocol import FileDownloadResponse, FileUploadResponse
from deepagents.backends.sandbox import BaseSandbox, ExecuteResponse
from opensandbox.exceptions import SandboxException
from opensandbox.models.execd import RunCommandOpts
from opensandbox.models.filesystem import WriteEntry


class OpenSandboxBackend(BaseSandbox):

    def __init__(self, sandbox):
        """保存已经创建的 OpenSandbox 实例。"""
        self.sandbox = sandbox

    @property
    def id(self) -> str:
        """读取当前沙箱编号。"""
        return self.sandbox.id

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        """
        在远端沙箱执行命令。

        Args:
            command - 要在沙箱中执行的 Shell 命令
            timeout - 超时秒数，省略时使用 60 秒
        Returns:
            包含标准输出、错误输出和实际退出码的执行结果。
        """
        result = self.sandbox.commands.run(command, opts=RunCommandOpts(timeout=timedelta(seconds=timeout or 60)))
        output = "".join(line.text for line in [*result.logs.stdout, *result.logs.stderr])
        if result.error:
            error_text = "\n".join([
                f"{result.error.name}: {result.error.value}",
                *result.error.traceback,
            ])
            if output and not output.endswith("\n"):
                output += "\n"
            output += error_text
        return ExecuteResponse(output=output, exit_code=result.exit_code)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """
        写文件到沙箱。

        Args:
            files - 沙箱绝对路径与文件字节的列表
        Returns:
            与输入顺序对应的上传结果；SDK 请求失败时抛出异常。
        """
        parents = {str(PurePosixPath(path).parent) for path, _ in files}
        self.sandbox.files.create_directories([WriteEntry(path=path) for path in parents])
        self.sandbox.files.write_files([WriteEntry(path=path, data=data, mode=644) for path, data in files])
        return [FileUploadResponse(path=path) for path, _ in files]

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """
        读沙箱文件。

        Args:
            paths - 沙箱文件路径列表
        Returns:
            按输入顺序返回文件字节，或对应的 SDK 错误。
        """
        results = []
        for path in paths:
            try:
                results.append(FileDownloadResponse(path=path, content=self.sandbox.files.read_bytes(path)))
            except SandboxException as error:
                results.append(FileDownloadResponse(path=path, error=str(error)))
        return results

    def close(self) -> None:
        """销毁远端沙箱容器并释放 SDK 连接，用户工作目录存储卷保留。"""
        self.sandbox.destroy()