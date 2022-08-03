from __future__ import annotations

from datetime import datetime, timedelta

import attrs
from dateutil.relativedelta import relativedelta


@attrs.define
class TimeRange:
    start: datetime
    end: datetime

    def contains_datetime(self, other: datetime, buffer: timedelta = None) -> bool:
        dt_buff = buffer or timedelta(seconds=0)
        start = self.start - dt_buff
        end = self.end + dt_buff
        return start <= other <= end

    @property
    def delta(self) -> relativedelta:
        return relativedelta(self.end, self.start)

    @property
    def timedelta(self) -> timedelta:
        return self.end - self.start

    @property
    def duration(self) -> str:
        fmt = "{}h {}m"
        return fmt.format(self.delta.hours, self.delta.minutes)

    @property
    def span(self) -> str:
        # date_fmt = '{:%-I}:{:%M}{:%p}'
        date_fmt = "{:%-I:%M%p}"
        return "-".join(
            [
                date_fmt.format(d)
                for d in (
                    self.start,
                    self.end,
                )
            ]
        )

    @staticmethod
    def as_day_and_time(in_dtime: datetime) -> str:
        date_fmt = "{:%b %d %-I:%M%p}"
        return date_fmt.format(in_dtime)

    @staticmethod
    def as_day(in_dtime: datetime) -> str:
        return "{:%b %d}".format(in_dtime)

    @property
    def day(self) -> str:
        return "{:%b %d}".format(self.start)
