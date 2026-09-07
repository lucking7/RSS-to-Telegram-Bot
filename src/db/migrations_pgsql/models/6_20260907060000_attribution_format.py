"""Separate attribution formatting from layout, preserving existing selections."""
from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "user" ADD "attribution_format" SMALLINT NOT NULL DEFAULT 0;
        ALTER TABLE "sub" ADD "attribution_format" SMALLINT NOT NULL DEFAULT -100;
        UPDATE "user" SET "attribution_format" = CASE "style" WHEN 2 THEN 1 WHEN 3 THEN 2 ELSE 0 END;
        UPDATE "sub" SET "attribution_format" = CASE "style" WHEN -100 THEN -100 WHEN 2 THEN 1 WHEN 3 THEN 2 ELSE 0 END;
        UPDATE "user" SET "style" = 0 WHERE "style" IN (2, 3);
        UPDATE "sub" SET "style" = 0 WHERE "style" IN (2, 3);
        UPDATE "user" SET "title_body_spacing" = 1 - "title_body_spacing" WHERE "title_body_spacing" IN (0, 1);
        UPDATE "sub" SET "title_body_spacing" = 1 - "title_body_spacing" WHERE "title_body_spacing" IN (0, 1);
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    # Layout/format combinations unavailable in the old version cannot be represented.
    # Production rollback restores the pre-migration DB backup instead.
    return """
        UPDATE "user" SET "style" = "attribution_format" + 1 WHERE "style" = 0 AND "attribution_format" IN (1, 2);
        UPDATE "sub" SET "style" = "attribution_format" + 1 WHERE "style" = 0 AND "attribution_format" IN (1, 2);
        UPDATE "user" SET "title_body_spacing" = 1 - "title_body_spacing" WHERE "title_body_spacing" IN (0, 1);
        UPDATE "sub" SET "title_body_spacing" = 1 - "title_body_spacing" WHERE "title_body_spacing" IN (0, 1);
        ALTER TABLE "sub" DROP COLUMN "attribution_format";
        ALTER TABLE "user" DROP COLUMN "attribution_format";
    """
