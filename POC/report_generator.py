# report_generator.py

from comparator_basic import BasicComparator
from basic_report import generate_basic_html_report

class ReportGenerator:
    """
    Dispatch basic-table report creation based on schema-specified 'reports'.
    """
    def __init__(self, schema: dict, data_ref: dict, data_tst: dict):
        """
        :param schema: dict mapping section names to {
                          'fields': { field_name: {...}, ... },
                          'reports': [ 'table', 'bar', ... ]
                       }
        :param data_ref: parsed reference data { section: [entry_dicts] }
        :param data_tst: parsed tested data    { section: [entry_dicts] }
        """
        self.schema   = schema
        self.data_ref = data_ref
        self.data_tst = data_tst

    def create(self, output_path: str):
        """
        Generate the HTML report at `output_path`. Uses:
          - BasicComparator to compute diffs
          - basic_report.generate_basic_html_report for rendering
        """
        # 1) Compute diffs for all sections
        comparator = BasicComparator(self.schema, self.data_ref, self.data_tst)
        diffs      = comparator.compare()

        # 2) Render full-data HTML, highlighting only the changed cells
        generate_basic_html_report(
            schema   = self.schema,
            data_ref = self.data_ref,
            data_tst = self.data_tst,
            diffs    = diffs,
            output_path = output_path
        )
