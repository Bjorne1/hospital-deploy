try:
    from .main import run
except ImportError:
    from hospital_deploy_tool.main import run


if __name__ == "__main__":
    raise SystemExit(run())
