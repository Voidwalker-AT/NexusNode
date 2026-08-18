"""
NexusNode — Docker Setup Integrity & Configuration Test Suite
Verifies Dockerfile, docker-compose.yml, .dockerignore, .env.example,
and persistent volume configurations conform to appliance security requirements.
"""

import os
import unittest


class TestDockerApplianceSetup(unittest.TestCase):
    """Verifies Docker infrastructure files and configuration standards."""

    @classmethod
    def setUpClass(cls):
        cls.root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cls.dockerfile_path = os.path.join(cls.root_dir, "Dockerfile")
        cls.compose_path = os.path.join(cls.root_dir, "docker-compose.yml")
        cls.dockerignore_path = os.path.join(cls.root_dir, ".dockerignore")
        cls.env_example_path = os.path.join(cls.root_dir, ".env.example")
        cls.docker_doc_path = os.path.join(cls.root_dir, "docs", "DOCKER.md")

    def test_dockerfile_exists_and_configured(self):
        """Dockerfile must exist with non-root security, FFmpeg, and healthcheck."""
        self.assertTrue(os.path.exists(self.dockerfile_path), "Dockerfile must exist.")
        with open(self.dockerfile_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("FROM python:", content)
        self.assertIn("ffmpeg", content, "Dockerfile must install FFmpeg.")
        self.assertIn("USER nexus", content, "Dockerfile must run as non-root user nexus.")
        self.assertIn("EXPOSE 5000", content, "Dockerfile must expose port 5000.")
        self.assertIn("HEALTHCHECK", content, "Dockerfile must define a container healthcheck.")
        self.assertIn("/api/health", content, "Healthcheck must target /api/health.")

    def test_dockerignore_excludes_sensitive_files(self):
        """.dockerignore must exclude databases, local storage vault, tests, and credentials."""
        self.assertTrue(os.path.exists(self.dockerignore_path), ".dockerignore must exist.")
        with open(self.dockerignore_path, "r", encoding="utf-8") as f:
            content = f.read()

        excluded_patterns = [
            "storage_vault/",
            "*.db",
            ".env",
            "tests/",
            "scratch/",
            "localtonet.log",
            "__pycache__/"
        ]
        for pattern in excluded_patterns:
            self.assertIn(pattern, content, f".dockerignore must exclude '{pattern}'")

    def test_compose_declares_services_and_volumes(self):
        """docker-compose.yml must define nexusnode, ollama, and named persistent volumes."""
        self.assertTrue(os.path.exists(self.compose_path), "docker-compose.yml must exist.")
        with open(self.compose_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("nexusnode:", content)
        self.assertIn("ollama:", content)
        self.assertIn("5000:5000", content)
        self.assertIn("11434:11434", content)
        self.assertIn("nexus_vault:", content, "Must declare nexus_vault named volume.")
        self.assertIn("nexus_logs:", content, "Must declare nexus_logs named volume.")
        self.assertIn("ollama_models:", content, "Must declare ollama_models named volume.")

    def test_env_example_template(self):
        """.env.example must exist with placeholder values."""
        self.assertTrue(os.path.exists(self.env_example_path), ".env.example must exist.")
        with open(self.env_example_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("SECRET_KEY", content)
        self.assertIn("NEXUS_ADMIN_PASSWORD", content)
        self.assertIn("OLLAMA_HOST", content)

    def test_docker_documentation_exists(self):
        """docs/DOCKER.md must exist and explain deployment."""
        self.assertTrue(os.path.exists(self.docker_doc_path), "docs/DOCKER.md must exist.")
        with open(self.docker_doc_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("Quickstart", content)
        self.assertIn("Persistent Storage", content)


if __name__ == "__main__":
    unittest.main()
