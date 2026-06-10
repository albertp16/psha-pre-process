from .converter import detect_format, convert_to_hmtk, read_phivolcs_excel, hmtk_to_csv_string
from .checker import (plot_catalogue_map, plot_depth_histogram,
                      plot_magnitude_time_scatter, plot_magnitude_time_density)
from .qaqc import find_duplicates, check_magnitude_consistency, find_gaps, plot_qaqc_summary
from .completeness import stepp_analysis, plot_stepp, plot_mag_time_density
