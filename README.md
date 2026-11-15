# Automated-Snack-Counter

Functional Requirements:
An Employee should be able to raise a snack refill request, then a request is assigned to someone based on least previous snack refills. Then the employee will fill snacks accordingly.
Employees should be able to raise a refund request and be able to track at individual stages and then get it reimbursed in a seamless way.
Generate a monthly report for the Blr and Oslo snack spending on request.
A chatbot to discuss the FAQs and maybe initiate the snack refill requests..

Non Functional Requirements, Functional TradeOffs and Assumptions:
1. Assuming that we are operating on low volume and constraints like avoiding refill accept duplication and validations w.r.t budget at different stages, I am choosing an SQL DB with mainly focused on consistency over availability(as minute unavailability is acceptable)
2. Once we assign a refill to an employee, he can reject it if he cannot volunteer and also will be reassigned to another employee if the request is not accepted in 2 days. Everything is logged.
3. Assuming the strict constraint on budget, every refill/refund requests get validated against monthly budget before they are initiated. For the same reason we are also not considering of completely automating the refill request as it might need additional sensors,
4. For reimbursement, use OCR and let the employee edit before submission.

Entities(Objects that are being used):
Employee (employee_id, name, payroll_currency, eligible_office_ids,refillCount)
Office (office_id, name, currency)
SnackCounter (counter_id, office_id, name)
RefillRequest (request_id, counter_id, requested_by, estimated_amount, status, created_at, current_assignment_id)
RefillAssignment (assignment_id, request_id, volunteer_id, status, assigned_at)
ReimbursementRequest (reimbursement_id, refill_request_id, employee_id, purchase_amount, purchase_currency, claim_amount, claim_currency, description, receipt_image, status, hr_claim_id)
MonthlyBudget (office_id, month, budget_amount)
AuditLog (log_id, entity_type, entity_id, action, actor_id, timestamp)

HLD/Functional Flow:

1. Chatbot : Currently has few predefined functionalities like maybe asking for a link for refill/refund requests,refill cancellation or maybe the monthly budget report, along with few FAQs. I didnt include any RAG Pipeline based LLM interaction as the useCases are only of a small sample(but I had previously worked on the chatbot with RAG, please refer to my public repos for the same). Selecting the options provided might trigger the actual functionalities of refill,refund,refill cancellation or report generation.

2. Refill: Once an employee finds the snack counter empty. They can click on the request refill option from the chatbot, then a request is triggered which fetches the users with min refillCount and randomly assigns to one of them.

3. refillCancellation: The user will be notified and has 2 days(assumption) to refill the snack counter, if they couldn’t do the same, they also have the option provided in an email to reject the refill request, it will be logged that the employee couldn’t refill at the moment and the user details are added in a list/vector field to the RefillRequest object. If it has been for more than 2 days without being claimed , then we are re assigning the refill request to another employee.
- We are making sure that there are no duplicates by using a status field(along with ACID principles also ensuring that we are following consistency over availability). The statuses follows these values:
UnAssigned -> UnClaimed -> Claimed -> InProgress -> Closed
4. Reimbursement: The employee will upload the receipt and then we will be using an OCR to automatically fill some/all of the details required for refund and provide the option to edit before submitting. The details are then validated against the budget constraints and an entry in the ReimbursementRequest object.
Statuses used : Approval Awaited -> Approved -> Refund Processed Successfully

5. Report: When the monthly budget is requested we are querying the ReimbursementRequest, Employee, and Monthly budget. Use the necessary fields to form a report and download the report.


How each problem is addressed : 

1.The box sits empty for days because everyone assumes someone else will refill it.
Ans. Once an employee notices the empty snack counter, they can raise a refill request via chatbot

2. Sometimes two people buy snacks on the same day.
Ans. we are maintaining statuses to track the refill, also using the ACID principle and consistency over availability

3. A few people do most of the refills and wait weeks to get their money back.
Ans. Have added statuses to track the refunds across the reimbursements.

4. Nobody knows how much is spent per month, or which snacks actually get eaten
Ans. The reimbursement and refill Details are used to make a report on demand
