import boto3
import csv
import os
import json
from datetime import datetime
from io import StringIO
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication

def format_recommendation_summaries(summaries, findings):
    resource_summary = {}
    for summary in summaries:
        resource_type = summary.get('group', 'Unknown')
        savings = float(summary.get('estimatedMonthlySavings', 0))
        
        # Get action types for this resource type from findings
        action_types = set()
        for finding in findings:
            if finding.get('currentResourceType') == resource_type:
                action_types.add(finding.get('actionType', 'Unknown'))
        
        if resource_type in resource_summary:
            resource_summary[resource_type]['savings'] += savings
            resource_summary[resource_type]['actions'].update(action_types)
        else:
            resource_summary[resource_type] = {
                'savings': savings,
                'actions': action_types
            }

    table_html = f"""
    <table border='1' style='border-collapse: collapse; width: 100%; margin-bottom: 20px;'>
        <tr style='background-color: #f2f2f2;'>
            <th style='padding: 12px; text-align: left;'>Resource Type</th>
            <th style='padding: 12px; text-align: left;'>Recommended Action</th>
            <th style='padding: 12px; text-align: right;'>Estimated Monthly Savings</th>
        </tr>"""

    total_savings = 0

    # Sort by savings for better visibility
    for resource_type, data in sorted(resource_summary.items(), 
                                    key=lambda x: x[1]['savings'], 
                                    reverse=True):
        savings = data['savings']
        actions = ', '.join(sorted(data['actions']))
        total_savings += savings
        
        table_html += f"""
        <tr>
            <td style='padding: 8px;'>{resource_type}</td>
            <td style='padding: 8px;'>{actions}</td>
            <td style='padding: 8px; text-align: right;'>${savings:,.2f}</td>
        </tr>
        """
    
    table_html += f"""
        <tr style='background-color: #f2f2f2; font-weight: bold;'>
            <td style='padding: 8px;'>Total</td>
            <td style='padding: 8px;'>-</td>
            <td style='padding: 8px; text-align: right;'>${total_savings:,.2f}</td>
        </tr>
    </table>
    """

    return table_html, total_savings

def get_bedrock_summary(summaries, findings):
    bedrock = boto3.client('bedrock-runtime', 'us-east-1')
    
    # Prepare the data for analysis
    summary_data = []
    for summary in summaries:
        summary_data.append({
            'resource_type': summary.get('group', 'Unknown'),
            'estimated_savings': summary.get('estimatedMonthlySavings', 0),
            'description': summary.get('description', '')
        })
    
    # Prepare findings data
    finding_data = []
    for finding in findings:
        finding_data.append({
            'resource_type': finding.get('currentResourceType', 'Unknown'),
            'action_type': finding.get('actionType', 'Unknown'),
            'estimated_savings': finding.get('estimatedMonthlySavings', 0),
            'resource_id': finding.get('resourceId', ''),
            'implementation_effort': finding.get('implementationEffort', '')
        })
    
    analysis_data = {
        "summaries": summary_data,
        "detailed_recommendations": finding_data
    }
    
    prompt = f"""Please analyze these AWS Cost Optimization recommendations and provide:
    1. Executive Summary:
       - Total potential monthly savings
       - Number of recommendations by resource type
       - Key action types identified
    
    2. Top 10 Recommendations:
       - Resource type and ID
       - Action type
       - Estimated savings
       - Implementation effort
    
    3. Quick Wins:
       - Low effort, high impact recommendations
       - Grouped by resource type
       - Specific action steps

    Please format the response with clear sections and bullet points.
    Highlight specific savings amounts and prioritize recommendations by ROI.

    Data for analysis:
    {json.dumps(analysis_data, default=str)}
    """
    
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 2000,
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.0
    })
    
    response = bedrock.invoke_model(
        modelId='anthropic.claude-3-sonnet-20240229-v1:0',
        body=body
    )
    
    response_body = json.loads(response['body'].read())
    return response_body['content'][0]['text']

def send_email(recipient, sender, subject, summaries, bedrock_summary, csv_data, findings):
    ses = boto3.client('ses', region_name='us-east-1')
    
    msg = MIMEMultipart('mixed')
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = recipient
    
    # Get summary table and total savings
    summary_table, total_savings = format_recommendation_summaries(summaries, findings)
    
    # Create the HTML part with styling
    html = f"""
    <html>
      <head>
        <style>
          body {{ 
            font-family: 'Segoe UI', Arial, sans-serif; 
            line-height: 1.6; 
            color: #2c3e50; 
            background-color: #f8f9fa;
          }}
          .container {{ 
            max-width: 800px; 
            margin: 0 auto; 
            padding: 30px;
            background-color: #ffffff;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            border-radius: 8px;
          }}
          h1 {{ 
            color: #2c3e50; 
            border-bottom: 3px solid #3498db; 
            padding-bottom: 15px;
            margin-bottom: 30px;
            font-size: 28px;
            text-align: center;
          }}
          h2 {{ 
            color: #2980b9; 
            margin-top: 30px;
            font-size: 22px;
            border-left: 4px solid #3498db;
            padding-left: 15px;
          }}
          .summary {{ 
            background-color: #ffffff; 
            padding: 20px;
            border-radius: 8px;
            margin: 25px 0;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
            border: 1px solid #e1e8ed;
          }}
          .recommendations {{ 
            margin-top: 30px;
            background-color: #ffffff;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
            border: 1px solid #e1e8ed;
          }}
          .total-savings {{ 
            background: linear-gradient(135deg, #43a047 0%, #2e7d32 100%);
            color: white;
            padding: 20px;
            border-radius: 8px;
            margin: 25px 0;
            text-align: center;
            font-size: 1.4em;
            font-weight: bold;
            box-shadow: 0 3px 6px rgba(0,0,0,0.1);
          }}
          .total-savings span {{
            font-size: 1.6em;
            display: block;
            margin-top: 10px;
          }}
          .footer-note {{
            margin-top: 30px;
            padding: 15px;
            background-color: #f8f9fa;
            border-radius: 8px;
            color: #666;
            text-align: center;
            font-style: italic;
          }}
        </style>
      </head>
      <body>
        <div class="container">
          <h1>AWS Cost Optimization Analysis</h1>
          
          <div class="total-savings">
            Potential Monthly Savings
            <span>${total_savings:,.2f}</span>
          </div>
          
          <div class="summary">
            <h2>Cost Optimization Summary by Resource Type</h2>
            {summary_table}
          </div>
          
          <div class="recommendations">
            <h2>Detailed Analysis and Recommendations</h2>
            <pre style="white-space: pre-wrap; background-color: #f8f9fa; padding: 15px; border-radius: 5px;">
{bedrock_summary}
            </pre>
          </div>
          
          <div class="footer-note">
            📎 A detailed CSV report is attached to this email for comprehensive analysis.
            Please review all recommendations carefully before implementation.
          </div>
        </div>
      </body>
    </html>
    """
    
    # Attach HTML and alternative plain text
    msg_alternative = MIMEMultipart('alternative')
    msg_alternative.attach(MIMEText(bedrock_summary, 'plain'))
    msg_alternative.attach(MIMEText(html, 'html'))
    msg.attach(msg_alternative)
    
    # Attach CSV file
    attachment = MIMEApplication(csv_data)
    attachment.add_header('Content-Disposition', 'attachment', 
                         filename=f'cost_optimization_recommendations_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv')
    msg.attach(attachment)
    
    try:
        response = ses.send_raw_email(
            Source=sender,
            Destinations=[recipient],
            RawMessage={'Data': msg.as_string()}
        )
        return response
    except Exception as e:
        print(f"Error sending email: {str(e)}")
        raise

def lambda_handler(event, context):
    # Initialize clients
    cost_hub = boto3.client('cost-optimization-hub', "us-east-1")
    s3_client = boto3.client('s3')
    
    bucket_name = os.environ.get('S3_BUCKET_NAME')
    email_recipient = os.environ.get('EMAIL_RECIPIENT')
    email_sender = os.environ.get('EMAIL_SENDER')
    
    try:
        print("Starting cost optimization analysis...")
        
        # Get recommendation summaries
        summaries = []
        paginator = cost_hub.get_paginator('list_recommendation_summaries')
        
        print("Fetching recommendation summaries...")
        page_iterator = paginator.paginate(
            groupBy="ResourceType"
        )
        
        for page in page_iterator:
            summaries.extend(page['items'])
        
        print(f"Found {len(summaries)} recommendation summaries")
        
        # Get detailed recommendations
        findings = []
        paginator = cost_hub.get_paginator('list_recommendations')
        
        print("Fetching detailed recommendations...")
        for page in paginator.paginate():
            for item in page['items']:
                recommendation_id = item['recommendationId']
                try:
                    detail = cost_hub.get_recommendation(
                        recommendationId=recommendation_id
                    )
                    findings.append(detail)
                except Exception as e:
                    print(f"Error getting recommendation details for {recommendation_id}: {str(e)}")
                    continue
        
        print(f"Found {len(findings)} detailed recommendations")
        
        if summaries and findings:
            print("Generating Bedrock analysis...")
            # Get Bedrock analysis
            bedrock_summary = get_bedrock_summary(summaries, findings)
            
            print("Creating CSV report...")
            # Create CSV
            csv_buffer = StringIO()
            if findings:
                # Get all unique keys from all findings
                all_keys = set()
                for finding in findings:
                    all_keys.update(finding.keys())
                
                writer = csv.DictWriter(csv_buffer, fieldnames=sorted(all_keys))
                writer.writeheader()
                writer.writerows(findings)
            csv_data = csv_buffer.getvalue()
            
            # Save CSV to S3
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            file_name = f'cost_optimization_recommendations_{timestamp}.csv'
            
            print(f"Saving CSV to S3: {file_name}")
            s3_client.put_object(
                Bucket=bucket_name,
                Key=file_name,
                Body=csv_data
            )
            
            print("Sending email...")
            # Send email with summary table, analysis, and CSV attachment
            email_subject = "AWS Cost Optimization Recommendations Summary"
            send_email(
                email_recipient,
                email_sender,
                email_subject,
                summaries,
                bedrock_summary,
                csv_data,
                findings
            )
            
            return {
                'statusCode': 200,
                'body': f'Successfully processed {len(findings)} recommendations and sent summary email'
            }
        else:
            print("No recommendations found")
            return {
                'statusCode': 200,
                'body': 'No cost optimization recommendations available'
            }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            'statusCode': 500,
            'body': f'Error processing recommendations: {str(e)}'
        }