from pipeline_common import stage_main
from content.render_common import render


def write(folder, inputs, metadata):
    return render(folder, inputs, metadata, 'articles', 'write_articles')


if __name__ == '__main__':
    raise SystemExit(stage_main('write_articles', write))
