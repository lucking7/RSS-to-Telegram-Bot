#  RSS to Telegram Bot
#  Copyright (C) 2021-2024  Rongrong <i@rong.moe>
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as
#  published by the Free Software Foundation, either version 3 of the
#  License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations
from typing import Optional, Any, NoReturn, Union
from typing_extensions import Final
from collections.abc import Callable

from collections import defaultdict
from contextlib import suppress
from math import ceil
from random import shuffle

from . import models
from .. import env, log

logger = log.getLogger('RSStT.db')


class __EffectiveOptions:
    """
    EffectiveOptions singleton class.

    Implement a write-through cache that caches all options to reduce db load.
    """
    __singleton: Optional["__EffectiveOptions"] = None
    __initialized: bool = False

    def __new__(cls, *args, **kwargs):
        if not cls.__singleton:
            cls.__singleton = super().__new__(cls)
        return cls.__singleton

    def __init__(self):
        if self.__initialized:
            return
        self.__initialized = True

        self.__options: dict[str, Union[str, int]] = {}
        self.__cached = False
        self.__default_options: dict[str, Union[str, int]] = {
            "default_interval": 10,
            "minimal_interval": 5,
            "user_sub_limit": -1,
            "channel_or_group_sub_limit": -1,
            "sub_limit_reached_message": "",
        }
        self.__callbacks: defaultdict[str, list[Callable[[str, Any], NoReturn]]] = defaultdict(list)

    @property
    def options(self) -> dict[str, Union[str, int]]:
        return self.__options.copy()

    @property
    def default_options(self) -> dict[str, Union[str, int]]:
        return self.__default_options.copy()

    @property
    def default_interval(self) -> int:
        return self.get('default_interval')

    @property
    def minimal_interval(self) -> int:
        return self.get("minimal_interval")

    @property
    def user_sub_limit(self) -> int:
        return self.get("user_sub_limit")

    @property
    def channel_or_group_sub_limit(self) -> int:
        return self.get("channel_or_group_sub_limit")

    @property
    def sub_limit_reached_message(self) -> str:
        return self.get("sub_limit_reached_message")

    def cast(self, key: str, value: Any, ignore_type_error: bool = False) -> Union[int, str, None]:
        if len(key) > 255:
            raise KeyError("Option key must be 255 characters or less")

        value_type = type(self.__default_options[key])

        if value is None:
            return "" if value_type is str else None

        try:
            return value_type(value)
        except (ValueError, TypeError) as e:
            if ignore_type_error:
                return self.__default_options[key]
            raise TypeError(f"Option value must be of type {value_type}") from e

    def get(self, key: str) -> Union[str, int]:
        """
        Get the value of an Option.

        :param key: option key
        :return: option value
        """
        if not self.__cached:
            raise RuntimeError("Options cache not initialized")
        return self.__options[key]

    async def set(self, key: str, value: Union[int, str]) -> NoReturn:
        """
        Set the value of an Option. (write-through to the DB)

        :param key: option key
        :param value: option value
        """
        value = self.cast(key, value)
        await models.Option.update_or_create(defaults={'value': str(value)}, key=key)
        self.__options[key] = value
        if key not in self.__callbacks:
            return
        for callback in self.__callbacks[key]:
            callback(key, value)

    async def cache(self) -> NoReturn:
        """
        Cache all options from the DB.
        """
        options = await models.Option.all()
        options = {o.key: o.value for o in options}

        for key, value in self.__default_options.items():
            if key in options:  # retrieved from db
                value = self.cast(key, options[key], ignore_type_error=True)  # cast using the type of default value
            self.__options[key] = value
            # await models.Option.create(key=key, value=value)  # init option
            if key not in self.__callbacks:
                continue
            for callback in self.__callbacks[key]:
                callback(key, value)

        self.__cached = True

    def add_set_callback(self, key: str, callback: Callable[[str, Any], NoReturn]) -> NoReturn:
        """
        Register a callback to be called when an option is set.

        :param key: option key
        :param callback: callback function
        """
        if key not in self.__default_options:
            raise KeyError("Invalid option key")
        self.__callbacks[key].append(callback)


EffectiveOptions = __EffectiveOptions()


def is_high_frequency_feed(link: Optional[str]) -> bool:
    if not link:
        return False
    normalized_link = link.lower()
    return any(pattern.lower() in normalized_link for pattern in env.HIGH_FREQUENCY_FEED_PATTERNS)


class EffectiveTasks:
    """
    EffectiveTasks class.

    A task dispatcher.
    """
    __task_buckets: dict[int, "EffectiveTasks"] = {}  # key: interval seconds, value: EffectiveTasks
    __all_tasks: dict[int, int] = {}  # key: id, value: interval seconds
    __feed_intervals: dict[int, int] = {}  # key: id, value: interval minutes

    def __init__(self, interval_secs: int) -> NoReturn:
        self.interval_secs: Final[int] = interval_secs
        self.__all_feeds: set[int] = set()
        self.__pending_feeds: list[int] = []  # use a list here to make randomization easier
        # self.__checked_feeds: set[int] = set()
        self.__run_count: int = 0

    @staticmethod
    def __ignore_key_or_value_error(func: Callable, *args, **kwargs) -> Optional[Any]:
        try:
            return func(*args, **kwargs)
        except (KeyError, ValueError):
            return None

    @classmethod
    async def init(cls, flush: bool = False) -> NoReturn:
        """
        Load a feeds from the DB and initialize tasks.

        :param flush: if already initialized, re-initialize?
        """
        if not cls.__task_buckets or flush:
            cls.__all_tasks = {}
            cls.__feed_intervals = {}
            cls.__task_buckets = {}
            feeds = await models.Feed.filter(state=1).values('id', 'interval', 'link')
            default_interval = EffectiveOptions.default_interval
            for feed in feeds:
                cls.update(feed_id=feed['id'], interval=feed['interval'] or default_interval, link=feed['link'])

    def __update(self, feed_id: int):
        self.__all_feeds.add(feed_id)
        # no need to add it to the pending list, since it will be processed in the next cycle
        #
        # if feed_id not in self.__pending_feeds:
        #     self.__pending_feeds.append(feed_id)

    @classmethod
    def get_interval_secs_for_feed(cls, interval: int, link: Optional[str] = None) -> int:
        interval_secs = (interval or EffectiveOptions.default_interval) * 60
        if is_high_frequency_feed(link):
            return min(interval_secs, env.HIGH_FREQUENCY_MONITOR_INTERVAL_SECS)
        return interval_secs

    @classmethod
    def update(cls, feed_id: int, interval: int = None, link: Optional[str] = None) -> NoReturn:
        """
        Update or add a task.

        :param feed_id: the id of the feed in the task
        :param interval: the interval of the task in minutes
        :param link: feed URL, used to apply high-frequency monitoring overrides
        """
        interval = interval or EffectiveOptions.default_interval
        interval_secs = cls.get_interval_secs_for_feed(interval, link)
        if feed_id in cls.__all_tasks:  # if already have a task
            if cls.__all_tasks[feed_id] == interval_secs and cls.__feed_intervals.get(feed_id) == interval:
                return
            cls.delete(feed_id, _preserve_in_all_tasks=True)  # delete the old one

        if interval_secs not in cls.__task_buckets:  # if lack of bucket
            cls.__task_buckets[interval_secs] = cls(interval_secs)  # create one

        cls.__all_tasks[feed_id] = interval_secs  # log the new task
        cls.__feed_intervals[feed_id] = interval
        cls.__task_buckets[interval_secs].__update(feed_id)  # update task

    def __delete(self, feed_id: int) -> NoReturn:
        self.__ignore_key_or_value_error(self.__all_feeds.remove, feed_id)
        self.__ignore_key_or_value_error(self.__pending_feeds.remove, feed_id)

    @classmethod
    def delete(cls, feed_id: int, _preserve_in_all_tasks: bool = False) -> NoReturn:
        """
        Delete a task.

        :param feed_id: the id of the feed in the task
        :param _preserve_in_all_tasks: for internal use
        """
        with suppress(KeyError):
            old_interval_secs = cls.__all_tasks[feed_id]
            cls.__task_buckets[old_interval_secs].__delete(feed_id)

            if not _preserve_in_all_tasks:
                del cls.__all_tasks[feed_id]
                with suppress(KeyError):
                    del cls.__feed_intervals[feed_id]

    @classmethod
    def exist(cls, feed_id: int) -> bool:
        """
        Check if a task exists.

        :param feed_id: the id of the feed in the task
        :return `bool`: if the task exists
        """
        return feed_id in cls.__all_tasks

    @classmethod
    def get_interval(cls, feed_id: int) -> Optional[int]:
        """
        Get the interval of a task.

        :param feed_id: the id of the feed in the task
        :return `int`: the interval of the task, or `None` if task do not exist
        """
        return cls.__feed_intervals[feed_id] if cls.exist(feed_id) else None

    @classmethod
    def get_interval_secs(cls, feed_id: int) -> Optional[int]:
        """
        Get the effective interval in seconds.

        :param feed_id: the id of the feed in the task
        :return `int`: the effective interval seconds, or `None` if task do not exist
        """
        return cls.__all_tasks[feed_id] if cls.exist(feed_id) else None

    def __get_tasks(self, monitor_interval_secs: int = 60) -> set[int]:
        if len(self.__all_feeds) == 0:
            return set()  # nothing to run
        run_count_limit = max(1, ceil(self.interval_secs / monitor_interval_secs))
        if self.__run_count == 0:
            self.__pending_feeds = list(self.__all_feeds)
            shuffle(self.__pending_feeds)  # randomize

        pop_count = ceil(len(self.__pending_feeds) / (run_count_limit - self.__run_count))
        # tasks_to_run = set(self.__pending_feeds.pop() for _ in range(pop_count) if self.__pending_feeds)
        tasks_to_run = set(self.__pending_feeds[:pop_count])
        del self.__pending_feeds[:pop_count]
        self.__run_count = self.__run_count + 1 if self.__run_count + 1 < run_count_limit else 0
        return tasks_to_run

    @classmethod
    def get_tasks(cls, monitor_interval_secs: int = 60) -> set[int]:
        """
        Get tasks to be run.

        :param monitor_interval_secs: seconds between scheduler ticks
        :return: a `set` contains the ids of feeds in tasks to be run
        """
        tasks_to_run = set()
        for effective_tasks in cls.__task_buckets.values():
            tasks = effective_tasks.__get_tasks(monitor_interval_secs=monitor_interval_secs)
            if tasks:
                tasks_to_run.update(tasks)

        return tasks_to_run


async def init():
    await EffectiveOptions.cache()
    await EffectiveTasks.init()
