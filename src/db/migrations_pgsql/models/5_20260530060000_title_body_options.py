#  RSS to Telegram Bot
#  Copyright (C) 2026  Rongrong <i@rong.moe>
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

from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "sub" ADD "title_body_spacing" SMALLINT NOT NULL  DEFAULT -100;
        ALTER TABLE "sub" ADD "auto_title_from_body" SMALLINT NOT NULL  DEFAULT -100;
        ALTER TABLE "user" ADD "title_body_spacing" SMALLINT NOT NULL  DEFAULT 0;
        ALTER TABLE "user" ADD "auto_title_from_body" SMALLINT NOT NULL  DEFAULT -1;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "user" DROP COLUMN "auto_title_from_body";
        ALTER TABLE "user" DROP COLUMN "title_body_spacing";
        ALTER TABLE "sub" DROP COLUMN "auto_title_from_body";
        ALTER TABLE "sub" DROP COLUMN "title_body_spacing";"""
