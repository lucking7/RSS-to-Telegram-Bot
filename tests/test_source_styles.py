"""Offline formatter regressions. Run: python -m tests.test_source_styles"""
import os
import unittest

os.environ.setdefault('TOKEN', 'test')
os.environ.setdefault('MANAGER', '-1')

from src.parsing.post_formatter import PostFormatter
from src import env


class SourceStylesTest(unittest.TestCase):
    def render(self, style=2, author='张三', feed_title='华尔街见闻·股市资讯', **options):
        async def run():
            formatter = PostFormatter(
                html='<p>正文内容</p>', title='文章标题', feed_title=feed_title,
                link=options.pop('link', 'https://example.com/article'), author=author,
            )
            formatter.telegraph_link = 'https://telegra.ph/example'
            result = await formatter.get_formatted_post(
                style=style, send_mode=options.pop('send_mode', 2),
                display_media=-1, **options,
            )
            return result[0]
        return env.loop.run_until_complete(run())

    def test_compact_footer(self):
        self.assertTrue(self.render().endswith(
            '<a href="https://example.com/article">华尔街见闻 · 股市资讯</a>｜张三'))

    def test_labeled_footer(self):
        self.assertTrue(self.render(style=3).endswith(
            '来源：<a href="https://example.com/article">华尔街见闻 · 股市资讯</a>｜作者：张三'))

    def test_legacy_footer_unchanged(self):
        self.assertTrue(self.render(style=0).endswith(
            'via <a href="https://example.com/article">华尔街见闻·股市资讯</a> (author: 张三)'))
        self.assertIn('(author: 张三)', self.render(style=1))

    def test_missing_and_hidden_authors(self):
        for style in (2, 3):
            for author in (None, '', '   '):
                with self.subTest(style=style, author=author):
                    result = self.render(style=style, author=author)
                    self.assertNotIn('｜', result)
                    self.assertNotIn('作者：', result)
            self.assertNotIn('张三', self.render(style=style, display_author=-1))

    def test_duplicate_author_auto_and_forced(self):
        self.assertNotIn('｜', self.render(author='华尔街见闻'))
        self.assertTrue(self.render(author='华尔街见闻', display_author=1).endswith('｜华尔街见闻'))

    def test_escaping(self):
        result = self.render(author='A&B <作者>', feed_title='A&B·<股市>')
        self.assertIn('A&amp;B · &lt;股市&gt;', result)
        self.assertTrue(result.endswith('｜A&amp;B &lt;作者&gt;'))

    def test_all_delivery_and_source_modes(self):
        for style in (2, 3):
            for send_mode in (0, 2, -1, 1):
                for display_via in (0, 1, -3, -1, -4, -2):
                    with self.subTest(style=style, mode=send_mode, via=display_via):
                        result = self.render(style=style, send_mode=send_mode, display_via=display_via)
                        self.assertNotIn('via ', result)
                        self.assertNotIn('(author:', result)
                        self.assertIn('张三', result)
                        if display_via == -2:
                            self.assertNotIn('华尔街见闻', result)
                        if send_mode == 1:
                            self.assertIn('https://telegra.ph/example', result)

    def test_body_end_author(self):
        for style in (2, 3):
            result = self.render(style=style, display_author=2)
            self.assertIn('正文内容 (张三)', result)
            self.assertEqual(result.count('张三'), 1)
            result = self.render(style=style, display_author=2, send_mode=-1)
            self.assertEqual(result.count('(张三)'), 1)

    def test_no_link_and_custom_subscription_title(self):
        self.assertTrue(self.render(link=None).endswith('华尔街见闻 · 股市资讯｜张三'))
        self.assertIn('自定义 · 名称', self.render(sub_title='自定义·名称'))

    def test_style_cache_isolation(self):
        async def run():
            formatter = PostFormatter(html='正文', feed_title='来源·分类', author='作者')
            results = []
            for style in (0, 2, 3, 0):
                results.append((await formatter.get_formatted_post(
                    style=style, send_mode=2, display_media=-1))[0])
            self.assertEqual(results[0], results[3])
            self.assertIn('via ', results[0])
            self.assertNotIn('via ', results[1])
            self.assertIn('来源：', results[2])
        env.loop.run_until_complete(run())

    def test_image_and_audio_survive_style_switch(self):
        from src.parsing.utils import Enclosure
        from src.parsing.medium import Image, Audio

        async def run():
            formatter = PostFormatter(
                html='<p>正文</p><img src="https://example.com/photo.jpg">',
                feed_title='来源', enclosures=[Enclosure('https://example.com/audio.mp3', _type='audio/mpeg')],
            )
            for style in (0, 1, 2, 3):
                await formatter.get_formatted_post(style=style, send_mode=2, display_media=-1)
                self.assertIsInstance(formatter.media.url_exists('https://example.com/photo.jpg'), Image)
                self.assertIsInstance(formatter.media.url_exists('https://example.com/audio.mp3'), Audio)
        env.loop.run_until_complete(run())

    def test_style_settings_persist_and_cycle(self):
        from tortoise import Tortoise
        from src import db
        from src.command.inner.customization import set_exhaustive_option, get_customization_buttons

        async def run():
            await Tortoise.init(db_url='sqlite://:memory:', modules={'models': ['src.db.models']})
            try:
                await Tortoise.generate_schemas()
                await db.EffectiveOptions.cache()
                user = await db.User.create(id=1)
                feed = await db.Feed.create(link='https://example.com/feed', title='来源')
                sub = await db.Sub.create(user=user, feed=feed, style=-100)
                for expected in (1, 0):
                    await set_exhaustive_option(user, 'style')
                    await user.refresh_from_db()
                    self.assertEqual(user.style, expected)
                for expected in (1, 2, 0):
                    await set_exhaustive_option(user, 'attribution_format')
                    await user.refresh_from_db()
                    self.assertEqual(user.attribution_format, expected)
                    for target in (user, sub):
                        buttons = await get_customization_buttons(target, lang='zh-Hans')
                        texts = [button.text for row in buttons for button in row]
                        self.assertTrue(any('来源与作者格式' in text for text in texts))
                for expected in (0, 1, -100):
                    await set_exhaustive_option(sub, 'style')
                    await sub.refresh_from_db()
                    self.assertEqual(sub.style, expected)
                for expected in (0, 1, 2, -100):
                    await set_exhaustive_option(sub, 'attribution_format')
                    await sub.refresh_from_db()
                    self.assertEqual(sub.attribution_format, expected)
                from unittest.mock import AsyncMock
                from types import SimpleNamespace
                from src.parsing.post import Post
                from src.command.customization import callback_reset, callback_reset_all
                user.attribution_format = 2
                await user.save()
                post = Post(html='正文', feed_link=feed.link)
                post.send_formatted_post = AsyncMock()
                await post.send_formatted_post_according_to_sub(sub)
                self.assertEqual(post.send_formatted_post.call_args.kwargs['attribution_format'], 2)
                sub.attribution_format = 1
                await sub.save()
                await post.send_formatted_post_according_to_sub(sub)
                self.assertEqual(post.send_formatted_post.call_args.kwargs['attribution_format'], 1)
                event = SimpleNamespace(is_private=False, chat_id=user.id, sender_id=user.id,
                                        data=f'reset={sub.id}'.encode(), edit=AsyncMock())
                await callback_reset.__wrapped__(event, lang='zh-Hans', chat_id=user.id)
                await sub.refresh_from_db()
                self.assertEqual(sub.attribution_format, -100)
                sub.attribution_format = 2
                await sub.save()
                await callback_reset_all.__wrapped__(event, lang='zh-Hans', chat_id=user.id)
                await sub.refresh_from_db()
                self.assertEqual(sub.attribution_format, -100)
            finally:
                await Tortoise.close_connections()
        env.loop.run_until_complete(run())


    def test_independent_layout_format_and_cache(self):
        async def run():
            fmt = PostFormatter(html='正文', title='标题', feed_title='来源·分类',
                                author='张三', link='https://example.com/article')
            fmt.telegraph_link = 'https://telegra.ph/example'
            for layout in (0, 1):
                for form in (0, 1, 2):
                    for mode in (0, 2, -1, 1):
                        for via in (0, 1, -1, -2, -3, -4):
                            text = (await fmt.get_formatted_post(
                                style=layout, attribution_format=form, send_mode=mode,
                                display_via=via, display_media=-1))[0]
                            self.assertIn('张三', text)
                            if form:
                                self.assertNotIn('(author:', text)
                                self.assertNotIn('via ', text)
                            if via == -2:
                                self.assertNotIn('来源', text)
                            if mode == 1:
                                self.assertIn('https://telegra.ph/example', text)
            compact = (await fmt.get_formatted_post(style=0, attribution_format=1, send_mode=2, display_media=-1))[0]
            labeled = (await fmt.get_formatted_post(style=0, attribution_format=2, send_mode=2, display_media=-1))[0]
            self.assertTrue(compact.endswith('｜张三'))
            self.assertTrue(labeled.endswith('｜作者：张三'))
            flowerss = (await fmt.get_formatted_post(style=1, attribution_format=1, send_mode=2, display_media=-1))[0]
            self.assertTrue(flowerss.startswith('<b>来源 · 分类</b>'))
        env.loop.run_until_complete(run())

    def test_paragraph_spacing(self):
        compact = self.render(style=0, title_body_spacing=0, display_title=1)
        spacious = self.render(style=0, title_body_spacing=1, display_title=1)
        self.assertIn('</b>\n正文内容', compact)
        self.assertIn('</b>\n\n正文内容', spacious)

    def test_migration_preserves_explicit_and_inherited_settings(self):
        import importlib.util
        import sqlite3
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        for backend in ('sqlite', 'pgsql'):
            file = root / f'src/db/migrations_{backend}/models/6_20260907060000_attribution_format.py'
            spec = importlib.util.spec_from_file_location('migration', file)
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)
            connection = sqlite3.connect(':memory:')
            try:
                connection.executescript(
                    'CREATE TABLE user (id INTEGER PRIMARY KEY, style INTEGER, title_body_spacing INTEGER);'
                    'CREATE TABLE sub (id INTEGER PRIMARY KEY, user_id INTEGER, style INTEGER, title_body_spacing INTEGER);')
                users, subs = [], []
                for user_style in (0, 1, 2, 3):
                    for spacing in (0, 1):
                        uid = len(users) + 1
                        users.append((uid, user_style, spacing))
                        for sub_style in (-100, 0, 1, 2, 3):
                            for sub_spacing in (-100, 0, 1):
                                subs.append((len(subs) + 1, uid, sub_style, sub_spacing))
                connection.executemany('INSERT INTO user VALUES (?,?,?)', users)
                connection.executemany('INSERT INTO sub VALUES (?,?,?,?)', subs)
                connection.executescript(env.loop.run_until_complete(migration.upgrade(None)))
                for uid, style, spacing in users:
                    self.assertEqual(connection.execute(
                        'SELECT style, attribution_format, title_body_spacing FROM user WHERE id=?', (uid,)).fetchone(),
                        (0 if style > 1 else style, style - 1 if style > 1 else 0, 1 - spacing))
                for sid, uid, style, spacing in subs:
                    expected_format = -100 if style == -100 else style - 1 if style > 1 else 0
                    self.assertEqual(connection.execute(
                        'SELECT style, attribution_format, title_body_spacing FROM sub WHERE id=?', (sid,)).fetchone(),
                        (0 if style > 1 else style, expected_format, -100 if spacing == -100 else 1 - spacing))
                connection.executescript(env.loop.run_until_complete(migration.downgrade(None)))
                self.assertEqual(connection.execute('SELECT * FROM user ORDER BY id').fetchall(), users)
                self.assertEqual(connection.execute('SELECT * FROM sub ORDER BY id').fetchall(), subs)
            finally:
                connection.close()


if __name__ == '__main__':
    unittest.main()
