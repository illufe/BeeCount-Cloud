from collections import defaultdict
from threading import Lock


# Prometheus histogram 默认 buckets(秒粒度)。请求耗时通常 < 1s,极端 > 5s
# 的是慢请求,grafana 配合可以画 P50 / P95 / P99 曲线。
_DEFAULT_DURATION_BUCKETS: tuple[float, ...] = (
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    float("inf"),
)


class InMemoryMetrics:
    """轻量内存指标。

    支持 unlabeled metric(老路径,`inc("name") / set_gauge("name", v)`)和
    labeled metric(`inc_labeled("name", {k: v}) / set_gauge_labeled(...)`)。
    新增 histogram 支持(`observe_histogram(name, value)`),按 Prometheus
    exposition 规范输出 `_bucket{le="..."} / _count / _sum` 三件套。
    `render_prometheus()` 按 metric name 合并 `# TYPE`,labeled 系列在同一
    name 下展开多行,符合 Prometheus exposition spec。
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: dict[str, float] = defaultdict(float)
        self._gauges: dict[str, float] = defaultdict(float)
        # labeled:name → {tuple(sorted label items)) → value}
        self._labeled_counters: dict[str, dict[tuple, float]] = defaultdict(dict)
        self._labeled_gauges: dict[str, dict[tuple, float]] = defaultdict(dict)
        # histogram:name → {buckets: list[float], counts: list[int],
        #                   sum: float, count: int}
        # 没用 labels(避免复杂度),如需 label 化 histogram 后续再扩展。
        self._histograms: dict[str, dict] = {}

    def inc(self, key: str, value: float = 1.0) -> None:
        with self._lock:
            self._counters[key] += value

    def set_gauge(self, key: str, value: float) -> None:
        with self._lock:
            self._gauges[key] = value

    def inc_labeled(
        self, name: str, labels: dict[str, str], value: float = 1.0
    ) -> None:
        """按 name + labels 累加 counter。labels 进 series key,name 共享 TYPE。"""
        label_key = self._normalize_labels(labels)
        with self._lock:
            self._labeled_counters[name].setdefault(label_key, 0.0)
            self._labeled_counters[name][label_key] += value

    def set_gauge_labeled(
        self, name: str, labels: dict[str, str], value: float
    ) -> None:
        label_key = self._normalize_labels(labels)
        with self._lock:
            self._labeled_gauges[name][label_key] = value

    def observe_histogram(
        self,
        name: str,
        value: float,
        buckets: tuple[float, ...] = _DEFAULT_DURATION_BUCKETS,
    ) -> None:
        """记一个 histogram 观测值。

        - `name` 不要带 `_bucket` / `_sum` / `_count` 后缀,render 时自动加。
        - `buckets` 是 le 阈值数组,默认是适合秒级耗时的分布,末尾必须有 inf。
        - **第一次使用某 name 后 buckets 不能改**(否则数据不一致),render 报错。
        """
        with self._lock:
            entry = self._histograms.get(name)
            if entry is None:
                entry = {
                    "buckets": buckets,
                    "counts": [0] * len(buckets),
                    "sum": 0.0,
                    "count": 0,
                }
                self._histograms[name] = entry
            elif entry["buckets"] != buckets:
                # 同 name 不同 buckets:静默用旧的,避免运行期 crash。日志这事
                # 上层调用方需要自己保证一致(单 helper / 单常量声明)。
                pass
            entry["sum"] += value
            entry["count"] += 1
            for i, le in enumerate(entry["buckets"]):
                if value <= le:
                    entry["counts"][i] += 1

    @staticmethod
    def _normalize_labels(labels: dict[str, str]) -> tuple[tuple[str, str], ...]:
        return tuple(sorted((k, str(v)) for k, v in labels.items()))

    @staticmethod
    def _format_labels(label_key: tuple[tuple[str, str], ...]) -> str:
        if not label_key:
            return ""
        parts = ",".join(f'{k}="{v}"' for k, v in label_key)
        return "{" + parts + "}"

    def render_prometheus(self) -> str:
        lines: list[str] = []
        with self._lock:
            for name, value in sorted(self._counters.items()):
                lines.append(f"# TYPE {name} counter")
                lines.append(f"{name} {value}")
            for name, value in sorted(self._gauges.items()):
                lines.append(f"# TYPE {name} gauge")
                lines.append(f"{name} {value}")
            for name in sorted(self._labeled_counters):
                lines.append(f"# TYPE {name} counter")
                for label_key, value in sorted(self._labeled_counters[name].items()):
                    lines.append(f"{name}{self._format_labels(label_key)} {value}")
            for name in sorted(self._labeled_gauges):
                lines.append(f"# TYPE {name} gauge")
                for label_key, value in sorted(self._labeled_gauges[name].items()):
                    lines.append(f"{name}{self._format_labels(label_key)} {value}")
            for name in sorted(self._histograms):
                entry = self._histograms[name]
                lines.append(f"# TYPE {name} histogram")
                # Prometheus 规范:_bucket 累计 + _sum + _count
                for le, cnt in zip(entry["buckets"], entry["counts"]):
                    le_label = "+Inf" if le == float("inf") else f"{le}"
                    lines.append(f'{name}_bucket{{le="{le_label}"}} {cnt}')
                lines.append(f"{name}_sum {entry['sum']}")
                lines.append(f"{name}_count {entry['count']}")
        return "\n".join(lines) + "\n"


metrics = InMemoryMetrics()
