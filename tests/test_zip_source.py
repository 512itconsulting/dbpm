from pathlib import Path
from zipfile import ZipFile

from dbpm.source import load_package_source


def test_load_package_from_zip(tmp_path: Path):
    archive_path = tmp_path / "demo.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "demo-0.1.0/dbpm.yaml",
            """
package:
  name: demo
  version: "0.1.0"

scripts:
  install: Deployment_Manifests/deploy.sql
""",
        )
        archive.writestr(
            "demo-0.1.0/META-INF/demo-build.properties",
            "git.commit.id=abcdefabcdefabcdefabcdefabcdefabcdefabcd\n",
        )

    source = load_package_source(str(archive_path))

    assert source.is_zip
    assert source.root == "demo-0.1.0"
    assert source.manifest.name == "demo"
    assert source.metadata["git.commit.id"] == "abcdefabcdefabcdefabcdefabcdefabcdefabcd"
    assert (
        source.resolve_script_path("Deployment_Manifests/deploy.sql")
        == "demo-0.1.0/Deployment_Manifests/deploy.sql"
    )
