"""Sector-specific financial RAG question catalogs for VN30 tickers."""

# ruff: noqa: E501
from __future__ import annotations

from dataclasses import dataclass
from typing import Final


# Keep the sector questionnaire catalog separate from the agent logic so the
# RAG pipeline stays readable while preserving the domain wording verbatim.


@dataclass(frozen=True)
class QuestionSection:
    title: str
    questions: tuple[str, ...]


@dataclass(frozen=True)
class SectorQuestionSet:
    key: str
    display_name: str
    sections: tuple[QuestionSection, ...]

    @property
    def all_questions(self) -> tuple[str, ...]:
        return tuple(question for section in self.sections for question in section.questions)


SECTION_TITLES: Final[tuple[str, ...]] = (
    "1. Kết quả kinh doanh & động lực biến động",
    "2. Chất lượng lợi nhuận & hiệu quả hoạt động",
    "3. Dòng tiền, bảng cân đối & chất lượng tài sản",
    "4. Rủi ro trọng yếu & kết luận kỳ báo cáo",
)

DEFAULT_SECTOR_KEY: Final[str] = "consumer"

SECTOR_MAP: Final[dict[str, tuple[str, ...]]] = {
    "bank": ("ACB", "BID", "CTG", "HDB", "LPB", "MBB", "SHB", "SSB", "STB", "TCB", "TPB", "VCB", "VIB", "VPB"),
    "securities": ("SSI",),
    "technology": ("FPT",),
    "steel": ("HPG",),
    "chemicals": ("DGC",),
    "energy": ("GAS", "PLX"),
    "consumer": ("MSN", "SAB", "VNM"),
    "retail": ("MWG",),
    "airline": ("VJC",),
    "residential_real_estate": ("VHM", "VIC"),
    "industrial_park": ("BCM", "GVR"),
    "retail_real_estate": ("VRE",),
}


SECTOR_QUESTIONS: Final[dict[str, tuple[str, ...]]] = {
    "bank": (
        "Thu nhập lãi thuần, lãi thuần dịch vụ, lãi thuần ngoại hối, lãi/lỗ chứng khoán và lợi nhuận sau thuế kỳ này biến động ra sao so với cùng kỳ?",
        "Thu nhập lãi và chi phí lãi biến động thế nào, và biến động đó gợi ý gì về áp lực biên lãi thuần trong kỳ?",
        "Tăng trưởng cho vay khách hàng trong kỳ là bao nhiêu, và cơ cấu dư nợ theo ngắn hạn, trung hạn, dài hạn thay đổi thế nào?",
        "Tiền gửi khách hàng, tiền gửi và vay các TCTD khác, phát hành giấy tờ có giá biến động ra sao; nguồn vốn tăng chủ yếu từ đâu?",
        "Thu nhập ngoài lãi kỳ này được dẫn dắt bởi hoạt động nào: dịch vụ, ngoại hối, chứng khoán, hoạt động khác hay thu nhập góp vốn?",

        "Chi phí hoạt động thay đổi như thế nào, và liệu biến động lợi nhuận có đi kèm với cải thiện hiệu quả vận hành không?",
        "Chi phí dự phòng rủi ro tín dụng biến động ra sao, và dự phòng đang là yếu tố hỗ trợ hay gây áp lực lên lợi nhuận kỳ này?",
        "Chất lượng nợ cho vay thay đổi thế nào qua các nhóm nợ 1 đến 5, đặc biệt là nợ nhóm 2 và nợ xấu?",
        "Dự phòng chung, dự phòng cụ thể và sử dụng dự phòng trong kỳ biến động ra sao; điều đó gợi ý gì về mức độ thận trọng trong trích lập?",
        "Lợi nhuận kế toán và cơ cấu thu nhập hiện tại phản ánh chủ yếu từ hoạt động cốt lõi hay bị ảnh hưởng đáng kể bởi các khoản thu nhập không thường xuyên?",

        "Lưu chuyển tiền thuần từ hoạt động kinh doanh là bao nhiêu, và các khoản mục nào kéo dòng tiền biến động mạnh nhất trong kỳ?",
        "Quan hệ giữa lợi nhuận sau thuế và dòng tiền từ hoạt động kinh doanh cho thấy điều gì về chất lượng lợi nhuận trong kỳ?",
        "Tổng tài sản, vốn chủ sở hữu và các khoản mục tài sản sinh lãi chính biến động ra sao so với đầu năm?",
        "Danh mục chứng khoán kinh doanh, chứng khoán đầu tư sẵn sàng để bán và giữ đến ngày đáo hạn thay đổi thế nào, và mức độ đóng góp/rủi ro từ danh mục này ra sao?",
        "Các khoản phải thu, lãi phí phải thu và tài sản có khác biến động thế nào; có dấu hiệu nào cần lưu ý về chất lượng tài sản nội bảng không?",

        "Tỷ lệ bao phủ nợ xấu ước tính ở mức nào dựa trên số liệu hiện có, và mức này cho thấy bộ đệm dự phòng đang mạnh hay chỉ ở mức trung bình?",
        "Cấu trúc kỳ hạn tài sản – nguồn vốn và bảng nhạy cảm lãi suất cho thấy rủi ro thanh khoản hoặc rủi ro lãi suất nổi bật ở đâu?",
        "Ngân hàng có phụ thuộc nhiều vào tiền gửi khách hàng, liên ngân hàng hay phát hành giấy tờ có giá để tài trợ tăng trưởng tài sản không?",
        "Các chỉ tiêu ngoài bảng như cam kết tín dụng, bảo lãnh, công cụ phái sinh và giao dịch với bên liên quan có điểm nào cần theo dõi thêm không?",
        "Kết luận kỳ này: chất lượng lợi nhuận, chất lượng tài sản và sức khỏe bảng cân đối của ngân hàng đang cải thiện, ổn định hay suy yếu?",
    ),

    "securities": (
        "Doanh thu hoạt động và lợi nhuận sau thuế kỳ này biến động ra sao so với cùng kỳ và so với đầu năm?",
        "Lợi nhuận kỳ này chủ yếu đến từ môi giới, cho vay ký quỹ, tự doanh, tư vấn hay doanh thu tài chính khác?",
        "Lãi/lỗ tài sản tài chính ghi nhận qua lãi lỗ, lãi/lỗ đầu tư và doanh thu tài chính thay đổi thế nào trong kỳ?",
        "Chi phí tài chính và chi phí hoạt động biến động ra sao; yếu tố nào đang chi phối mạnh nhất lợi nhuận kỳ này?",
        "Nếu có doanh thu môi giới, cho vay ký quỹ hoặc dịch vụ chứng khoán, cơ cấu đóng góp của từng mảng thay đổi ra sao?",

        "Biên lợi nhuận hoạt động kỳ này thay đổi thế nào và nguyên nhân chủ yếu đến từ doanh thu hay chi phí?",
        "Lợi nhuận hiện tại phản ánh năng lực tạo lợi nhuận từ hoạt động cốt lõi hay bị ảnh hưởng lớn bởi đánh giá lại/tái phân loại tài sản tài chính?",
        "Các khoản dự phòng giảm giá tài sản tài chính, phải thu hoặc tổn thất tín dụng biến động thế nào trong kỳ?",
        "Hiệu quả sử dụng vốn chủ sở hữu trong kỳ có được cải thiện hay không, xét trên biến động lợi nhuận và quy mô vốn?",
        "Cơ cấu doanh thu hiện tại có cân bằng hay đang phụ thuộc nhiều vào một nguồn thu dễ biến động?",

        "Lưu chuyển tiền từ hoạt động kinh doanh, đầu tư và tài chính biến động ra sao; dòng tiền nào đang quyết định thay đổi tiền ròng kỳ này?",
        "Quan hệ giữa lợi nhuận sau thuế và dòng tiền kinh doanh cho thấy chất lượng lợi nhuận hiện tại mạnh hay yếu?",
        "Quy mô tài sản tài chính ngắn hạn, các khoản cho vay, phải thu và đầu tư nắm giữ đến ngày đáo hạn thay đổi thế nào?",
        "Nợ vay ngắn hạn, dài hạn và chi phí lãi vay biến động ra sao; đòn bẩy tài chính đang tăng hay giảm?",
        "Các khoản phải thu, ứng trước, tài sản dở dang hoặc tài sản khác có điểm nào cần lưu ý về khả năng thu hồi không?",

        "Danh mục tài sản tài chính hiện tại tập trung vào nhóm nào và mức độ nhạy cảm với biến động thị trường thể hiện qua đâu?",
        "Nguồn vốn của công ty ổn định chủ yếu nhờ vốn chủ sở hữu hay phụ thuộc đáng kể vào nợ vay ngắn hạn?",
        "Có dấu hiệu nào cho thấy lợi nhuận bị làm mượt bởi ghi nhận đánh giá lại, bán tài sản hoặc hoàn nhập dự phòng không?",
        "Các giao dịch với bên liên quan, cam kết ngoại bảng hoặc nghĩa vụ tiềm tàng có rủi ro đáng chú ý không?",
        "Kết luận kỳ này: công ty chứng khoán đang thể hiện chất lượng lợi nhuận tốt, trung bình hay yếu trên nền bảng cân đối hiện tại?",
    ),

    "technology": (
        "Doanh thu thuần, lợi nhuận gộp, lợi nhuận thuần và lợi nhuận sau thuế kỳ này biến động ra sao so với cùng kỳ?",
        "Biến động doanh thu trong kỳ phản ánh chủ yếu từ tăng sản lượng dịch vụ, thay đổi cơ cấu doanh thu hay ghi nhận các khoản khác?",
        "Biên lợi nhuận gộp thay đổi thế nào và yếu tố nào trong báo cáo đang gợi ý nguyên nhân chính của sự thay đổi đó?",
        "Doanh thu tài chính, chi phí tài chính và lãi/lỗ khác có đóng góp đáng kể vào lợi nhuận kỳ này không?",
        "Mức tăng trưởng lợi nhuận kỳ này có đi cùng với tăng trưởng doanh thu hay chủ yếu đến từ tối ưu chi phí?",

        "Chi phí bán hàng và chi phí quản lý doanh nghiệp biến động ra sao; doanh nghiệp có đang cải thiện hiệu quả vận hành không?",
        "Lợi nhuận hiện tại phản ánh hoạt động cốt lõi hay chịu tác động lớn từ thu nhập tài chính, hoàn nhập hoặc các khoản bất thường?",
        "Biên lợi nhuận hoạt động và biên lợi nhuận ròng đang cải thiện, đi ngang hay suy giảm?",
        "Nếu báo cáo có thuyết minh theo mảng hoặc doanh thu chưa thực hiện, cơ cấu đóng góp của từng mảng đang thay đổi thế nào?",
        "Chất lượng lợi nhuận có đáng tin cậy không khi đối chiếu giữa lợi nhuận kế toán và các khoản dồn tích như phải thu, doanh thu chưa thực hiện?",

        "Lưu chuyển tiền từ hoạt động kinh doanh có theo sát tăng trưởng lợi nhuận không?",
        "Các khoản phải thu khách hàng, chi phí trả trước, tài sản dở dang và doanh thu chưa thực hiện biến động ra sao trong kỳ?",
        "Tiền và tương đương tiền, đầu tư tài chính ngắn hạn/dài hạn và nợ vay thay đổi thế nào; bảng cân đối đang mạnh lên hay yếu đi?",
        "Capex thể hiện qua tài sản cố định, tài sản dở dang hoặc chi phí xây dựng cơ bản dở dang có tăng mạnh không?",
        "Doanh nghiệp đang tài trợ tăng trưởng bằng dòng tiền nội bộ hay bằng nợ vay/vốn huy động thêm?",

        "Có dấu hiệu nào về áp lực thu hồi công nợ hoặc kéo dài vòng quay tiền mặt trong kỳ không?",
        "Tỷ lệ đòn bẩy, chi phí lãi vay và nghĩa vụ nợ hiện tại có tạo áp lực đáng kể lên lợi nhuận các kỳ tới không?",
        "Các khoản mục ngoài hoạt động cốt lõi như đầu tư tài chính, công ty liên kết, góp vốn có đang ảnh hưởng đáng kể đến kết quả hợp nhất không?",
        "Các giao dịch với bên liên quan, cam kết hoặc nghĩa vụ tiềm tàng có điểm nào cần lưu ý từ góc nhìn nhà phân tích BCTC không?",
        "Kết luận kỳ này: doanh nghiệp công nghệ đang thể hiện tăng trưởng chất lượng cao, tăng trưởng dựa vào tài chính hay tăng trưởng nhưng cash conversion còn yếu?",
    ),

    "steel": (
        "Doanh thu thuần, giá vốn, lợi nhuận gộp, lợi nhuận thuần và lợi nhuận sau thuế biến động ra sao so với cùng kỳ?",
        "Biến động doanh thu kỳ này đến nhiều hơn từ thay đổi sản lượng tiêu thụ hay thay đổi giá bán bình quân, dựa trên thuyết minh hiện có?",
        "Biên lợi nhuận gộp thay đổi thế nào và báo cáo đang gợi ý tác động chủ yếu từ giá vốn nguyên liệu hay từ cơ cấu sản phẩm?",
        "Doanh thu tài chính, chi phí tài chính và lãi/lỗ khác có đóng góp lớn vào lợi nhuận kỳ này không?",
        "Kết quả kinh doanh hiện tại đang được hỗ trợ chủ yếu bởi hoạt động cốt lõi hay bởi yếu tố phi hoạt động?",

        "Chi phí bán hàng, chi phí quản lý và chi phí lãi vay biến động ra sao; doanh nghiệp có đang cải thiện hiệu quả vận hành không?",
        "Lợi nhuận hiện tại có chất lượng tốt không khi đối chiếu giữa lợi nhuận gộp, lợi nhuận ròng và dòng tiền kinh doanh?",
        "Biên EBIT/biên lợi nhuận ròng đang phục hồi hay suy giảm so với cùng kỳ?",
        "Nếu có dự phòng giảm giá hàng tồn kho hoặc hoàn nhập dự phòng, tác động của khoản này lên lợi nhuận là gì?",
        "Chi phí lãi vay và đòn bẩy tài chính có đang làm khuếch đại biến động lợi nhuận không?",

        "Dòng tiền từ hoạt động kinh doanh biến động thế nào, và hàng tồn kho, phải thu, phải trả đang tác động ra sao đến dòng tiền?",
        "Hàng tồn kho tăng/giảm như thế nào; điều đó gợi ý tích trữ nguyên liệu, thành phẩm chậm tiêu thụ hay chuẩn bị cho chu kỳ sản xuất mới?",
        "Các khoản phải thu khách hàng và phải trả người bán thay đổi ra sao; chu kỳ vốn lưu động đang cải thiện hay xấu đi?",
        "Tài sản cố định, chi phí xây dựng cơ bản dở dang và đầu tư dự án mới có tăng mạnh không?",
        "Doanh nghiệp đang tài trợ tồn kho và capex bằng dòng tiền nội bộ hay bằng nợ vay?",

        "Cơ cấu nợ ngắn hạn, dài hạn và áp lực chi phí lãi vay hiện tại có đáng lo không?",
        "Có dấu hiệu nào cho thấy lợi nhuận bị méo bởi các khoản bất thường như thanh lý tài sản, đánh giá lại hoặc hoàn nhập dự phòng không?",
        "Chất lượng bảng cân đối hiện tại mạnh hay yếu khi xét đồng thời tiền mặt, tồn kho, nợ vay và vốn chủ sở hữu?",
        "Những rủi ro tài chính nổi bật nhất trong kỳ thể hiện qua BCTC là gì: tồn kho, đòn bẩy, cash conversion hay biên lợi nhuận?",
        "Kết luận kỳ này: doanh nghiệp thép đang ở pha hồi phục vận hành, ổn định, hay lợi nhuận vẫn còn rất nhạy với chu kỳ hàng hóa?",
    ),

    "chemicals": (
        "Doanh thu thuần, lợi nhuận gộp, lợi nhuận thuần và lợi nhuận sau thuế kỳ này biến động ra sao so với cùng kỳ?",
        "Biến động doanh thu và lợi nhuận kỳ này gợi ý tác động mạnh hơn từ giá bán, sản lượng hay cơ cấu sản phẩm?",
        "Biên lợi nhuận gộp thay đổi thế nào và giá vốn hàng bán đang tác động ra sao đến hiệu quả kinh doanh?",
        "Doanh thu tài chính, chi phí tài chính, lãi/lỗ khác có ảnh hưởng đáng kể tới lợi nhuận kỳ này không?",
        "Kết quả hiện tại phản ánh chủ yếu từ hoạt động cốt lõi hay từ các khoản thu nhập không thường xuyên?",

        "Chi phí bán hàng và chi phí quản lý doanh nghiệp biến động ra sao; hiệu quả vận hành có được cải thiện không?",
        "Biên lợi nhuận hoạt động và biên lợi nhuận ròng đang mở rộng hay thu hẹp?",
        "Nếu có hoàn nhập hoặc trích lập dự phòng tồn kho, phải thu hoặc đầu tư tài chính, tác động của các khoản này lên lợi nhuận là gì?",
        "Lợi nhuận hiện tại có chất lượng tốt không khi đối chiếu với dòng tiền từ hoạt động kinh doanh?",
        "Mức độ phụ thuộc của lợi nhuận vào doanh thu tài chính, lãi chênh lệch tỷ giá hoặc thu nhập khác có cao không?",

        "Dòng tiền từ hoạt động kinh doanh biến động thế nào; hàng tồn kho, phải thu và phải trả đang kéo dòng tiền ra sao?",
        "Hàng tồn kho tăng/giảm như thế nào; có dấu hiệu tích trữ nguyên liệu hoặc chậm tiêu thụ thành phẩm không?",
        "Các khoản phải thu khách hàng, trả trước và tài sản dở dang có tăng bất thường không?",
        "Tiền mặt, đầu tư tài chính, nợ vay và vốn chủ sở hữu thay đổi thế nào; bảng cân đối đang mạnh lên hay yếu đi?",
        "Chi phí xây dựng cơ bản dở dang hoặc tài sản cố định tăng mạnh có phản ánh giai đoạn mở rộng công suất không?",

        "Đòn bẩy tài chính và chi phí lãi vay hiện tại có gây áp lực đáng kể lên lợi nhuận các kỳ tới không?",
        "Có dấu hiệu nào cho thấy lợi nhuận bị làm mượt bởi hoàn nhập dự phòng, thanh lý tài sản hoặc ghi nhận một lần không?",
        "Chất lượng tài sản hiện tại cần lưu ý ở điểm nào nhất: tiền, tồn kho, phải thu hay đầu tư tài chính?",
        "Rủi ro tài chính nổi bật nhất thể hiện qua BCTC kỳ này là gì: biên gộp giảm, hàng tồn kho tăng, phải thu tăng hay nợ vay tăng?",
        "Kết luận kỳ này: doanh nghiệp hóa chất đang cho thấy chất lượng lợi nhuận tốt, trung bình hay lợi nhuận còn phụ thuộc mạnh vào biến động giá vốn?",
    ),

    "energy": (
        "Doanh thu thuần, lợi nhuận gộp, lợi nhuận thuần và lợi nhuận sau thuế kỳ này biến động ra sao so với cùng kỳ?",
        "Biến động doanh thu và lợi nhuận hiện tại gợi ý tác động lớn hơn từ sản lượng, giá bán hay biến động giá vốn hàng hóa?",
        "Biên lợi nhuận gộp thay đổi thế nào và giá vốn có đang là yếu tố chi phối mạnh nhất kết quả kỳ này không?",
        "Doanh thu tài chính, chi phí tài chính, lãi/lỗ chênh lệch tỷ giá hoặc lãi/lỗ khác có ảnh hưởng lớn đến lợi nhuận không?",
        "Kết quả hiện tại phản ánh chủ yếu từ hoạt động kinh doanh cốt lõi hay bị ảnh hưởng nhiều bởi yếu tố ngoài hoạt động?",

        "Chi phí bán hàng, chi phí quản lý và chi phí lãi vay biến động ra sao; hiệu quả vận hành có được cải thiện không?",
        "Lợi nhuận hiện tại có chất lượng tốt không khi so sánh với dòng tiền từ hoạt động kinh doanh?",
        "Nếu có dự phòng giảm giá hàng tồn kho hoặc hoàn nhập, tác động của khoản mục này lên lợi nhuận là gì?",
        "Biên lợi nhuận ròng đang cải thiện, đi ngang hay suy giảm?",
        "Mức độ phụ thuộc vào doanh thu/chi phí tài chính trong cơ cấu lợi nhuận hiện tại có cao không?",

        "Dòng tiền từ hoạt động kinh doanh thay đổi ra sao; tồn kho, phải thu, phải trả và biến động giá hàng hóa đang kéo dòng tiền như thế nào?",
        "Hàng tồn kho biến động ra sao; mức tồn kho hiện tại gợi ý lợi thế hay rủi ro trong bối cảnh giá hàng hóa thay đổi?",
        "Các khoản phải thu, ứng trước và công nợ thương mại có tăng bất thường không?",
        "Tiền mặt, đầu tư tài chính, nợ vay và vốn chủ sở hữu biến động thế nào; bảng cân đối có đủ sức chống chịu không?",
        "Capex thể hiện qua tài sản cố định, tài sản dở dang hoặc dự án lớn có đang tăng mạnh không?",

        "Cơ cấu nợ ngắn hạn – dài hạn và chi phí lãi vay hiện tại có tạo áp lực lên lợi nhuận các kỳ tới không?",
        "Có dấu hiệu nào cho thấy lợi nhuận bị méo bởi ghi nhận một lần, thanh lý tài sản, đánh giá lại hoặc hoàn nhập dự phòng không?",
        "Chất lượng tài sản hiện tại cần lưu ý nhất ở khoản mục nào: hàng tồn kho, phải thu, đầu tư tài chính hay tài sản dở dang?",
        "Rủi ro tài chính nổi bật nhất thể hiện qua BCTC kỳ này là gì: biến động biên gộp, vốn lưu động, đòn bẩy hay dòng tiền?",
        "Kết luận kỳ này: doanh nghiệp năng lượng/xăng dầu/khí đang thể hiện lợi nhuận cốt lõi tốt, lợi nhuận biến động theo hàng hóa hay chất lượng cash flow còn cần theo dõi thêm?",
    ),

    "consumer": (
        "Doanh thu thuần, lợi nhuận gộp, lợi nhuận thuần và lợi nhuận sau thuế kỳ này biến động ra sao so với cùng kỳ?",
        "Biến động doanh thu hiện tại gợi ý doanh nghiệp đang tăng trưởng chủ yếu nhờ sản lượng, giá bán hay thay đổi cơ cấu sản phẩm?",
        "Biên lợi nhuận gộp thay đổi thế nào và giá vốn hàng bán đang tác động ra sao tới kết quả kinh doanh?",
        "Doanh thu tài chính, chi phí tài chính và lãi/lỗ khác có ảnh hưởng đáng kể đến lợi nhuận kỳ này không?",
        "Kết quả hiện tại phản ánh chủ yếu từ hoạt động cốt lõi hay có đóng góp lớn từ các khoản không thường xuyên?",

        "Chi phí bán hàng và chi phí quản lý doanh nghiệp biến động ra sao; hiệu quả vận hành có được cải thiện không?",
        "Biên lợi nhuận hoạt động và biên lợi nhuận ròng đang cải thiện hay suy giảm?",
        "Nếu có hoàn nhập hoặc trích lập dự phòng hàng tồn kho, phải thu hay đầu tư tài chính, tác động đến lợi nhuận là gì?",
        "Lợi nhuận hiện tại có chất lượng tốt không khi đối chiếu với dòng tiền từ hoạt động kinh doanh?",
        "Mức độ phụ thuộc vào doanh thu tài chính, lãi chênh lệch tỷ giá hoặc thu nhập khác trong cơ cấu lợi nhuận hiện tại có cao không?",

        "Dòng tiền từ hoạt động kinh doanh biến động thế nào; hàng tồn kho, phải thu và phải trả đang tác động ra sao đến dòng tiền?",
        "Hàng tồn kho tăng/giảm như thế nào; điều đó gợi ý thay đổi nhu cầu tiêu thụ, chính sách dự trữ hay rủi ro hàng chậm luân chuyển?",
        "Các khoản phải thu khách hàng, trả trước cho người bán và tài sản ngắn hạn khác có tăng bất thường không?",
        "Tiền mặt, đầu tư tài chính, nợ vay và vốn chủ sở hữu biến động ra sao; bảng cân đối có đang mạnh lên không?",
        "Capex hoặc tài sản dở dang có tăng mạnh không; doanh nghiệp đang mở rộng hay đang tối ưu tài sản hiện hữu?",

        "Đòn bẩy tài chính và chi phí lãi vay hiện tại có gây áp lực lên lợi nhuận các kỳ tới không?",
        "Có dấu hiệu nào cho thấy lợi nhuận bị làm mượt bởi hoàn nhập, thanh lý tài sản, đánh giá lại hoặc ghi nhận một lần không?",
        "Chất lượng tài sản hiện tại cần lưu ý ở điểm nào nhất: tồn kho, phải thu, tiền mặt hay đầu tư tài chính?",
        "Rủi ro tài chính nổi bật nhất trong kỳ thể hiện qua BCTC là gì: biên gộp, hàng tồn kho, công nợ, đòn bẩy hay dòng tiền?",
        "Kết luận kỳ này: doanh nghiệp tiêu dùng đang thể hiện tăng trưởng vận hành lành mạnh, tăng trưởng nhờ yếu tố tài chính hay chất lượng lợi nhuận còn cần theo dõi?",
    ),

    "retail": (
        "Doanh thu thuần, lợi nhuận gộp, lợi nhuận thuần và lợi nhuận sau thuế kỳ này biến động ra sao so với cùng kỳ?",
        "Biến động doanh thu hiện tại gợi ý tăng trưởng đến nhiều hơn từ mở rộng quy mô hay từ cải thiện hiệu quả bán hàng hiện hữu?",
        "Biên lợi nhuận gộp thay đổi thế nào và giá vốn hàng bán đang tác động ra sao tới lợi nhuận?",
        "Doanh thu tài chính, chi phí tài chính và thu nhập/lỗ khác có ảnh hưởng lớn tới kết quả kỳ này không?",
        "Kết quả hiện tại phản ánh chủ yếu từ hoạt động bán lẻ cốt lõi hay có đóng góp lớn từ yếu tố ngoài hoạt động?",

        "Chi phí bán hàng và chi phí quản lý doanh nghiệp biến động ra sao; hiệu quả vận hành có được cải thiện không?",
        "Biên lợi nhuận hoạt động và biên lợi nhuận ròng đang cải thiện hay vẫn chịu áp lực?",
        "Nếu có hoàn nhập hoặc trích lập dự phòng hàng tồn kho, phải thu, tác động đến lợi nhuận là gì?",
        "Lợi nhuận hiện tại có chất lượng tốt không khi so sánh với dòng tiền từ hoạt động kinh doanh?",
        "Cơ cấu lợi nhuận hiện tại có phụ thuộc lớn vào doanh thu tài chính hoặc các khoản một lần không?",

        "Dòng tiền từ hoạt động kinh doanh biến động thế nào; tồn kho, phải thu và phải trả đang kéo dòng tiền ra sao?",
        "Hàng tồn kho tăng/giảm như thế nào; có dấu hiệu tích hàng, giảm tốc tiêu thụ hay cải thiện vòng quay không?",
        "Các khoản phải thu, trả trước cho người bán và tài sản ngắn hạn khác có tăng bất thường không?",
        "Tiền mặt, đầu tư tài chính, nợ vay và vốn chủ sở hữu thay đổi thế nào; sức khỏe bảng cân đối đang cải thiện hay suy yếu?",
        "Chi phí xây dựng cơ bản dở dang, tài sản cố định hoặc tài sản thuê hoạt động có tăng mạnh không; doanh nghiệp còn đang mở rộng mạnh không?",

        "Đòn bẩy tài chính và chi phí lãi vay hiện tại có gây áp lực đáng kể lên lợi nhuận các kỳ tới không?",
        "Có dấu hiệu nào cho thấy lợi nhuận bị làm mượt bởi hoàn nhập chi phí, thanh lý tài sản hoặc khoản thu nhập không thường xuyên không?",
        "Chất lượng tài sản hiện tại cần lưu ý nhất ở khoản mục nào: tồn kho, phải thu, tài sản dở dang hay tiền mặt?",
        "Rủi ro tài chính nổi bật nhất trong kỳ thể hiện qua BCTC là gì: tồn kho, biên gộp, đòn bẩy hay cash conversion?",
        "Kết luận kỳ này: doanh nghiệp bán lẻ đang phục hồi vận hành thật, ổn định, hay lợi nhuận vẫn dễ biến động do cấu trúc vốn lưu động?",
    ),

    "airline": (
        "Doanh thu thuần, lợi nhuận gộp, lợi nhuận thuần và lợi nhuận sau thuế kỳ này biến động ra sao so với cùng kỳ?",
        "Biến động doanh thu hiện tại gợi ý thay đổi lớn hơn từ hoạt động vận tải cốt lõi hay từ các nguồn thu khác?",
        "Biên lợi nhuận gộp thay đổi thế nào và giá vốn đang tác động ra sao tới kết quả kinh doanh?",
        "Doanh thu tài chính, chi phí tài chính, chênh lệch tỷ giá và lãi/lỗ khác có ảnh hưởng lớn tới lợi nhuận kỳ này không?",
        "Kết quả hiện tại phản ánh chủ yếu từ hoạt động vận hành cốt lõi hay từ các khoản không thường xuyên?",

        "Chi phí bán hàng, chi phí quản lý và đặc biệt chi phí tài chính biến động ra sao; hiệu quả vận hành có cải thiện không?",
        "Biên lợi nhuận hoạt động và biên lợi nhuận ròng đang cải thiện hay vẫn chịu áp lực?",
        "Nếu có ghi nhận hoàn nhập, đánh giá lại, thanh lý tài sản hoặc giao dịch một lần, tác động của khoản đó lên lợi nhuận là gì?",
        "Lợi nhuận hiện tại có chất lượng tốt không khi so sánh với dòng tiền từ hoạt động kinh doanh?",
        "Mức độ phụ thuộc vào doanh thu tài chính hoặc các khoản mục ngoài hoạt động trong cơ cấu lợi nhuận có cao không?",

        "Dòng tiền từ hoạt động kinh doanh, đầu tư và tài chính biến động ra sao; dòng tiền nào đang chi phối thay đổi tiền ròng kỳ này?",
        "Các khoản phải thu, trả trước, phải trả và doanh thu chưa thực hiện thay đổi thế nào; có dấu hiệu nào cần lưu ý về chất lượng lợi nhuận không?",
        "Tiền mặt, nợ vay ngắn hạn, nợ vay dài hạn và vốn chủ sở hữu biến động ra sao; bảng cân đối có đang chịu áp lực không?",
        "Tài sản cố định, tài sản quyền sử dụng, tài sản dở dang hoặc đặt cọc dài hạn có tăng mạnh không?",
        "Doanh nghiệp đang tài trợ đầu tư và nghĩa vụ tài chính bằng dòng tiền nội bộ hay tiếp tục dựa nhiều vào nợ?",

        "Chi phí lãi vay và chênh lệch tỷ giá hiện tại có phải là rủi ro lớn với lợi nhuận các kỳ tới không?",
        "Có dấu hiệu nào cho thấy lợi nhuận bị méo bởi giao dịch bất thường, thanh lý tài sản hoặc các khoản tài chính một lần không?",
        "Chất lượng tài sản hiện tại cần lưu ý nhất ở khoản mục nào: phải thu, tài sản dở dang, đặt cọc, nợ vay hay vốn lưu động?",
        "Rủi ro tài chính nổi bật nhất trong kỳ thể hiện qua BCTC là gì: đòn bẩy, chi phí tài chính, dòng tiền hay nghĩa vụ đầu tư?",
        "Kết luận kỳ này: hãng hàng không đang cải thiện chất lượng lợi nhuận thật, chỉ hồi phục kế toán, hay bảng cân đối vẫn còn áp lực lớn?",
    ),

    "residential_real_estate": (
        "Doanh thu thuần, lợi nhuận gộp, lợi nhuận thuần và lợi nhuận sau thuế kỳ này biến động ra sao so với cùng kỳ?",
        "Biến động doanh thu kỳ này gợi ý ghi nhận chủ yếu từ bàn giao bất động sản, chuyển nhượng, doanh thu tài chính hay hoạt động khác?",
        "Biên lợi nhuận gộp thay đổi thế nào và báo cáo đang gợi ý tác động từ cơ cấu dự án hoặc chi phí vốn hóa ra sao?",
        "Doanh thu tài chính, chi phí tài chính, lãi/lỗ khác có ảnh hưởng lớn đến lợi nhuận kỳ này không?",
        "Kết quả hiện tại phản ánh sức khỏe hoạt động cốt lõi hay bị chi phối nhiều bởi khoản mục ngoài hoạt động?",

        "Chi phí bán hàng, chi phí quản lý và chi phí lãi vay biến động ra sao; hiệu quả vận hành có được cải thiện không?",
        "Lợi nhuận hiện tại có chất lượng tốt không khi so sánh với dòng tiền từ hoạt động kinh doanh?",
        "Nếu có hoàn nhập dự phòng, đánh giá lại, thanh lý hoặc chuyển nhượng khoản đầu tư, tác động của khoản này lên lợi nhuận là gì?",
        "Biên lợi nhuận hoạt động và biên lợi nhuận ròng đang cải thiện hay suy giảm?",
        "Cơ cấu lợi nhuận hiện tại có phụ thuộc nhiều vào doanh thu tài chính hoặc thu nhập khác không?",

        "Dòng tiền từ hoạt động kinh doanh biến động thế nào; hàng tồn kho, phải thu, người mua trả tiền trước và phải trả đang tác động ra sao?",
        "Hàng tồn kho, chi phí xây dựng cơ bản dở dang hoặc bất động sản dở dang tăng/giảm như thế nào trong kỳ?",
        "Người mua trả tiền trước, doanh thu chưa thực hiện hoặc các khoản nhận trước thay đổi ra sao; điều đó gợi ý gì về tiến độ bán hàng và thu tiền?",
        "Các khoản phải thu, hợp tác kinh doanh, đầu tư vào công ty con/liên kết có tăng bất thường không?",
        "Tiền mặt, nợ vay ngắn hạn, nợ vay dài hạn, trái phiếu và vốn chủ sở hữu biến động ra sao; bảng cân đối đang mạnh lên hay yếu đi?",

        "Chi phí lãi vay và mức độ đòn bẩy hiện tại có tạo áp lực đáng kể lên lợi nhuận các kỳ tới không?",
        "Có dấu hiệu nào cho thấy lợi nhuận bị làm mượt bởi ghi nhận một lần, thanh lý, đánh giá lại hoặc hoàn nhập dự phòng không?",
        "Chất lượng tài sản hiện tại cần lưu ý nhất ở khoản mục nào: tồn kho dự án, phải thu, dòng tiền hay cấu trúc nợ?",
        "Rủi ro tài chính nổi bật nhất trong kỳ thể hiện qua BCTC là gì: tồn kho lớn, phải thu cao, dòng tiền yếu hay đòn bẩy cao?",
        "Kết luận kỳ này: doanh nghiệp bất động sản nhà ở đang cải thiện vận hành thật, chỉ ghi nhận lợi nhuận kế toán, hay bảng cân đối vẫn cần theo dõi chặt?",
    ),

    "industrial_park": (
        "Doanh thu thuần, lợi nhuận gộp, lợi nhuận thuần và lợi nhuận sau thuế kỳ này biến động ra sao so với cùng kỳ?",
        "Biến động doanh thu kỳ này gợi ý đến từ cho thuê đất, cho thuê hạ tầng, doanh thu xây dựng, dịch vụ hay khoản ghi nhận khác?",
        "Biên lợi nhuận gộp thay đổi thế nào và giá vốn/doanh thu bất động sản khu công nghiệp đang tác động ra sao tới lợi nhuận?",
        "Doanh thu tài chính, chi phí tài chính và lãi/lỗ khác có ảnh hưởng đáng kể tới kết quả kỳ này không?",
        "Kết quả hiện tại phản ánh chủ yếu từ hoạt động cốt lõi hay từ các khoản tài chính và một lần?",

        "Chi phí bán hàng, chi phí quản lý và chi phí lãi vay biến động ra sao; hiệu quả vận hành có được cải thiện không?",
        "Lợi nhuận hiện tại có chất lượng tốt không khi đối chiếu với dòng tiền từ hoạt động kinh doanh?",
        "Nếu có chuyển nhượng, thanh lý, đánh giá lại hoặc hoàn nhập dự phòng, tác động lên lợi nhuận là gì?",
        "Biên lợi nhuận hoạt động và biên lợi nhuận ròng đang cải thiện hay suy giảm?",
        "Cơ cấu lợi nhuận hiện tại có phụ thuộc nhiều vào doanh thu tài chính hoặc thu nhập khác không?",

        "Dòng tiền từ hoạt động kinh doanh biến động thế nào; phải thu, người mua trả tiền trước, hàng tồn kho và chi phí dở dang đang tác động ra sao?",
        "Chi phí xây dựng cơ bản dở dang, bất động sản dở dang, tài sản cố định và tài sản dài hạn khác biến động như thế nào?",
        "Các khoản phải thu khách hàng, phải thu hợp tác, ứng trước bồi thường giải phóng mặt bằng có tăng bất thường không?",
        "Tiền mặt, nợ vay, trái phiếu, vốn chủ sở hữu và quỹ đất ghi sổ thể hiện trên bảng cân đối thay đổi ra sao?",
        "Nguồn vốn cho đầu tư hạ tầng hiện tại đến chủ yếu từ dòng tiền nội bộ, người mua trả trước hay nợ vay?",

        "Chi phí lãi vay và mức độ đòn bẩy hiện tại có gây áp lực đáng kể lên lợi nhuận và dòng tiền các kỳ tới không?",
        "Có dấu hiệu nào cho thấy lợi nhuận bị làm mượt bởi ghi nhận một lần, chuyển nhượng hoặc hoàn nhập dự phòng không?",
        "Chất lượng tài sản hiện tại cần lưu ý nhất ở khoản mục nào: phải thu, chi phí dở dang, tiền thu trước hay nợ vay?",
        "Rủi ro tài chính nổi bật nhất trong kỳ thể hiện qua BCTC là gì: vốn lưu động, đòn bẩy, cash flow hay tiến độ ghi nhận?",
        "Kết luận kỳ này: doanh nghiệp khu công nghiệp đang thể hiện chất lượng lợi nhuận tốt, lợi nhuận mang tính ghi nhận kế toán, hay bảng cân đối vẫn cần theo dõi thêm?",
    ),

    "retail_real_estate": (
        "Doanh thu thuần, lợi nhuận gộp, lợi nhuận thuần và lợi nhuận sau thuế kỳ này biến động ra sao so với cùng kỳ?",
        "Biến động doanh thu kỳ này gợi ý đến từ cho thuê mặt bằng, dịch vụ liên quan, chuyển nhượng hay doanh thu tài chính?",
        "Biên lợi nhuận gộp thay đổi thế nào và giá vốn/chi phí vận hành tài sản cho thuê đang tác động ra sao tới lợi nhuận?",
        "Doanh thu tài chính, chi phí tài chính và lãi/lỗ khác có ảnh hưởng lớn đến kết quả kỳ này không?",
        "Kết quả hiện tại phản ánh chủ yếu từ hoạt động cho thuê cốt lõi hay từ các khoản ngoài hoạt động?",

        "Chi phí bán hàng, chi phí quản lý và chi phí lãi vay biến động ra sao; hiệu quả vận hành có được cải thiện không?",
        "Lợi nhuận hiện tại có chất lượng tốt không khi so sánh với dòng tiền từ hoạt động kinh doanh?",
        "Nếu có hoàn nhập, thanh lý, đánh giá lại hoặc khoản ghi nhận một lần, tác động lên lợi nhuận là gì?",
        "Biên lợi nhuận hoạt động và biên lợi nhuận ròng đang cải thiện hay suy giảm?",
        "Cơ cấu lợi nhuận hiện tại có phụ thuộc lớn vào doanh thu tài chính hoặc thu nhập khác không?",

        "Dòng tiền từ hoạt động kinh doanh biến động thế nào; phải thu khách thuê, doanh thu chưa thực hiện, phải trả và chi phí dở dang đang tác động ra sao?",
        "Các khoản phải thu ngắn hạn, dài hạn và tài sản dở dang liên quan đến trung tâm thương mại biến động như thế nào?",
        "Doanh thu chưa thực hiện, người thuê trả trước hoặc nghĩa vụ liên quan đến khách thuê thay đổi ra sao trong kỳ?",
        "Tiền mặt, nợ vay, chi phí lãi vay, tài sản cố định đầu tư và vốn chủ sở hữu biến động thế nào?",
        "Chi phí xây dựng cơ bản dở dang hoặc tài sản đầu tư mới có tăng mạnh không; doanh nghiệp có đang mở rộng tài sản cho thuê không?",

        "Đòn bẩy tài chính và chi phí lãi vay hiện tại có gây áp lực đáng kể lên lợi nhuận các kỳ tới không?",
        "Có dấu hiệu nào cho thấy lợi nhuận bị làm mượt bởi ghi nhận một lần, chuyển nhượng, hoàn nhập hoặc khoản tài chính không?",
        "Chất lượng tài sản hiện tại cần lưu ý nhất ở khoản mục nào: phải thu khách thuê, tài sản dở dang, nợ vay hay dòng tiền?",
        "Rủi ro tài chính nổi bật nhất trong kỳ thể hiện qua BCTC là gì: áp lực tài trợ tài sản, cash flow, công nợ hay hiệu quả tài sản cho thuê?",
        "Kết luận kỳ này: doanh nghiệp bất động sản bán lẻ đang cho thấy chất lượng lợi nhuận tốt, ổn định, hay vẫn phụ thuộc nhiều vào cấu trúc vốn và tiến độ tài sản?",
    ),
}


def _build_question_set(key: str, display_name: str, questions: tuple[str, ...]) -> SectorQuestionSet:
    if len(questions) != 20:
        raise ValueError(f"Sector {key} must define exactly 20 questions, got {len(questions)}")

    sections = tuple(
        QuestionSection(
            title=SECTION_TITLES[index],
            questions=questions[index * 5 : (index + 1) * 5],
        )
        for index in range(len(SECTION_TITLES))
    )
    return SectorQuestionSet(key=key, display_name=display_name, sections=sections)

QUESTION_SETS: Final[dict[str, SectorQuestionSet]] = {
    "bank": _build_question_set("bank", "Ngân hàng", SECTOR_QUESTIONS["bank"]),
    "securities": _build_question_set("securities", "Chứng khoán", SECTOR_QUESTIONS["securities"]),
    "technology": _build_question_set("technology", "Công nghệ", SECTOR_QUESTIONS["technology"]),
    "steel": _build_question_set("steel", "Thép / Vật liệu cơ bản", SECTOR_QUESTIONS["steel"]),
    "chemicals": _build_question_set("chemicals", "Hóa chất", SECTOR_QUESTIONS["chemicals"]),
    "energy": _build_question_set("energy", "Năng lượng khí / Xăng dầu", SECTOR_QUESTIONS["energy"]),
    "consumer": _build_question_set("consumer", "Hàng tiêu dùng / Thực phẩm / Đồ uống", SECTOR_QUESTIONS["consumer"]),
    "retail": _build_question_set("retail", "Bán lẻ", SECTOR_QUESTIONS["retail"]),
    "airline": _build_question_set("airline", "Hàng không", SECTOR_QUESTIONS["airline"]),
    "residential_real_estate": _build_question_set(
        "residential_real_estate",
        "Bất động sản nhà ở / Đại đô thị",
        SECTOR_QUESTIONS["residential_real_estate"],
    ),
    "industrial_park": _build_question_set(
        "industrial_park",
        "Bất động sản khu công nghiệp",
        SECTOR_QUESTIONS["industrial_park"],
    ),
    "retail_real_estate": _build_question_set(
        "retail_real_estate",
        "Bất động sản bán lẻ / Trung tâm thương mại",
        SECTOR_QUESTIONS["retail_real_estate"],
    ),
}

TICKER_TO_SECTOR: Final[dict[str, str]] = {
    ticker: sector_key
    for sector_key, tickers in SECTOR_MAP.items()
    for ticker in tickers
}


def get_sector_key_for_ticker(ticker: str) -> str:
    return TICKER_TO_SECTOR.get(ticker.upper(), DEFAULT_SECTOR_KEY)


def get_question_set_for_ticker(ticker: str) -> SectorQuestionSet:
    sector_key = get_sector_key_for_ticker(ticker)
    return QUESTION_SETS[sector_key]
