import asyncio
import subprocess
from asyncio import create_task, sleep
from typing import TypeVar, Sequence

from nonebot import get_driver, logger
from typing_extensions import ParamSpec

T = TypeVar('T')
P = ParamSpec('P')

class HostProber:
    def __init__(self, mirrors: Sequence[str]):
        self._mirrors = mirrors
        self._host = mirrors[0]
        self._select_host_daemon_task = None

        get_driver().on_startup(self.start)
        get_driver().on_shutdown(self.close)

    async def start(self):
        self._select_host_daemon_task = create_task(self._select_host_daemon())
        logger.info("Host prober daemon started.")

    async def close(self):
        if self._select_host_daemon_task:
            self._select_host_daemon_task.cancel()
            logger.info("Host prober daemon stopped.")

    @property
    def host(self) -> str:
        return self._host

    async def select_host(self, exclude_current: bool = False) -> bool:
        logger.debug("Host selection started...")

        ping_tasks = []
        for h in self._mirrors:
            if exclude_current and h == self._host:
                continue
            ping_task = create_task(self.ping_host(h))
            ping_tasks.append((h, ping_task))

        selected = None
        selected_result = None

        for host, ping_task in ping_tasks:
            try:
                success, result = await ping_task
                if success:
                    logger.debug(f"Ping to {host} completed: {result}")

                    # You can modify this part to compare results, such as RTT or packet loss
                    if selected is None or result < selected_result:
                        selected = host
                        selected_result = result
                        logger.info(f"New best host selected: {host} with RTT: {result} ms")
                else:
                    logger.warning(f"Ping to {host} failed: {result}")

            except Exception as e:
                logger.warning(f"Ping to {host} failed due to error: {e}. Exception type: {type(e)}")

        if selected:
            if selected != self._host:
                logger.info(f"Switching active host to: {selected}")
                self._host = selected
                logger.info(f"Active host changed to {self._host} with RTT: {selected_result} ms")
            return True
        else:
            logger.error("No viable host found after pinging all mirrors.")
            return False

    async def ping_host(self, host: str):
        try:
            # 使用 subprocess 调用系统的 ping 命令
            result = await asyncio.create_subprocess_exec(
                "ping", "-c", "4", host,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            stdout, stderr = await result.communicate()

            if result.returncode == 0:
                # 解析输出结果
                output = stdout.decode('utf-8')
                # 提取 RTT 时间并返回
                # 示例：提取平均 RTT 时间
                avg_rtt = self.extract_avg_rtt(output)
                return True, avg_rtt  # 返回成功和 RTT 时间
            else:
                return False, stderr.decode('utf-8')
        except Exception as e:
            return False, str(e)

    def extract_avg_rtt(self, ping_output: str):
        # 解析 ping 命令的输出，提取平均 RTT
        import re
        match = re.search(r'avg = (\d+\.\d+) ms', ping_output)
        if match:
            return float(match.group(1))
        return float('inf')  # 如果无法提取，则返回无限大

    async def _select_host_daemon(self):
        while True:
            try:
                logger.debug("Host selection daemon running...")
                # 尝试选择一个新的主机
                if await self.select_host():
                    logger.info("Host selection completed successfully. Waiting for next check.")
                    await sleep(600)  # 每10分钟检查一次
                else:
                    logger.error("Failed to select a new host. Retrying in 60 seconds.")
                    await sleep(60)  # 每60秒重试一次
            except Exception as e:
                logger.exception(f"Unexpected error occurred in host selection daemon: {e}")
                await sleep(60)  # 如果出现异常，等60秒再重试

