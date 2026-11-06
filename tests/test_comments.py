import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import server


class CommentTests(unittest.TestCase):
    def test_sqlite_schema_stores_comments_with_author_and_post(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "forum.db"
            server.init_db(database_path)

            with closing(server.connect_db(database_path)) as db:
                user = db.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    ("testare", "test-hash"),
                )
                post = db.execute(
                    "INSERT INTO posts (user_id, body) VALUES (?, ?)",
                    (user.lastrowid, "Ett inlägg"),
                )
                db.execute(
                    "INSERT INTO comments (post_id, user_id, body) VALUES (?, ?, ?)",
                    (post.lastrowid, user.lastrowid, "En kommentar"),
                )
                db.commit()
                comment = db.execute(
                    "SELECT comments.body, users.username, posts.body AS post_body "
                    "FROM comments "
                    "JOIN users ON users.id = comments.user_id "
                    "JOIN posts ON posts.id = comments.post_id"
                ).fetchone()

            self.assertEqual(comment["body"], "En kommentar")
            self.assertEqual(comment["username"], "testare")
            self.assertEqual(comment["post_body"], "Ett inlägg")

    def test_comments_render_inside_collapsible_section_and_are_escaped(self):
        post = {"id": 12}
        comments = [
            {
                "username": "<script>namn</script>",
                "created_at": "2026-11-06 11:00:00",
                "body": "<b>kommentar</b>",
            }
        ]

        html = server.ForumHandler._comments_section(
            post, comments, {"id": 1}, "csrf-token"
        )

        self.assertIn("<details class=\"comments\">", html)
        self.assertIn("Visa kommentarer (1)", html)
        self.assertIn("name=\"post_id\" value=\"12\"", html)
        self.assertIn("&lt;script&gt;namn&lt;/script&gt;", html)
        self.assertIn("&lt;b&gt;kommentar&lt;/b&gt;", html)
        self.assertNotIn("<script>namn</script>", html)

    def test_empty_comments_show_count_and_login_prompt(self):
        html = server.ForumHandler._comments_section(
            {"id": 1}, [], None, "csrf-token"
        )

        self.assertIn("Visa kommentarer (0)", html)
        self.assertIn("Inga kommentarer ännu.", html)
        self.assertIn('href="/login"', html)
        self.assertNotIn('action="/comment"', html)

    def test_comments_are_removed_when_their_post_is_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "forum.db"
            server.init_db(database_path)

            with closing(server.connect_db(database_path)) as db:
                user = db.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    ("testare", "test-hash"),
                )
                post = db.execute(
                    "INSERT INTO posts (user_id, body) VALUES (?, ?)",
                    (user.lastrowid, "Ett inlägg"),
                )
                db.execute(
                    "INSERT INTO comments (post_id, user_id, body) VALUES (?, ?, ?)",
                    (post.lastrowid, user.lastrowid, "En kommentar"),
                )
                db.execute("DELETE FROM posts WHERE id = ?", (post.lastrowid,))
                remaining = db.execute("SELECT COUNT(*) FROM comments").fetchone()[0]

            self.assertEqual(remaining, 0)


if __name__ == "__main__":
    unittest.main()
