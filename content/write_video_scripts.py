from pipeline_common import stage_main
from content.render_common import render


def write(folder, inputs, metadata):
    return render(folder, inputs, metadata, 'video_scripts', 'write_video_scripts')


if __name__ == '__main__':
    raise SystemExit(stage_main('write_video_scripts', write))
