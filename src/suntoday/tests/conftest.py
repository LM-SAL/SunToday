import pytest

mpl_svg_compare = pytest.mark.mpl_image_compare(savefig_kwargs={"format": "svg"})
