/** The category palette shared by Spending's "By category" bars and budget bars. */
export const CATEGORY_COLORS = ['#2DD4A7', '#38BDF8', '#A78BFA', '#FBBF24', '#FB7185', '#34D399', '#818CF8', '#F472B6']

export const categoryColor = (index: number) => CATEGORY_COLORS[index % CATEGORY_COLORS.length]
