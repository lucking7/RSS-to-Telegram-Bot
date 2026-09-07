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
                for expected in (1, 2, 3, 0):
                    await set_exhaustive_option(user, 'style')
                    await user.refresh_from_db()
                    self.assertEqual(user.style, expected)
                    if expected in (2, 3):
                        for target in (user, sub):
                            buttons = await get_customization_buttons(target, lang='zh-Hans')
                            texts = [button.text for row in buttons for button in row]
                            self.assertTrue(any(('简洁来源' if expected == 2 else '来源标签') in text for text in texts))
                for expected in (0, 1, 2, 3, -100):
                    await set_exhaustive_option(sub, 'style')
                    await sub.refresh_from_db()
                    self.assertEqual(sub.style, expected)
            finally:
                await Tortoise.close_connections()
        env.loop.run_until_complete(run())


if __name__ == '__main__':
    unittest.main()
